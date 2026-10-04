"""Typed extraction with validation and bounded retry.

Provider output is untrusted. It is validated against:

1. the extraction envelope (:class:`_Envelope`)
2. the Domain Pack observation schema for every observation (generated Pydantic
   models, ``extra="forbid"``)
3. the pending question's field spec for answers

Invalid output is retried at most ``max_attempts`` times with the validation error
fed back. After that the result is empty and the errors are recorded - output is
never silently coerced into something Cairn did not validate.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from cairn.ai.provider import AIProvider, AIProviderError, ExtractionRequest
from cairn.domain_packs.observation_models import validate_field_value, validate_fields
from cairn.domain_packs.pack import DomainPack
from cairn.observability.logging import get_logger

EXTRACTION_VERSION = "1.0.0"

log = get_logger(__name__)


class _EnvelopeObservation(BaseModel):
    observation_type: str
    fields: dict[str, Any]
    confidence: float | None = Field(default=None, ge=0, le=1)


class _EnvelopeAnswer(BaseModel):
    field: str
    value: Any = None
    declined: bool = False


class _Envelope(BaseModel):
    new_observations: list[_EnvelopeObservation] = Field(default_factory=list)
    answer: _EnvelopeAnswer | None = None


class ExtractedObservation(BaseModel):
    observation_type: str
    observation_schema_version: str
    fields: dict[str, Any]
    confidence: float | None


class ExtractedAnswer(BaseModel):
    field: str
    value: Any
    declined: bool


class ExtractionResult(BaseModel):
    new_observations: list[ExtractedObservation] = Field(default_factory=list)
    answer: ExtractedAnswer | None = None
    provider: str
    model: str
    extraction_version: str = EXTRACTION_VERSION
    attempts: int
    errors: list[str] = Field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.errors) and not self.new_observations and self.answer is None


class ExtractionService:
    def __init__(self, provider: AIProvider, *, max_attempts: int = 2) -> None:
        self._provider = provider
        self._max_attempts = max_attempts

    async def extract(self, pack: DomainPack, request: ExtractionRequest) -> ExtractionResult:
        errors: list[str] = []
        provider_name, model = self._provider.name, "unknown"
        for attempt in range(1, self._max_attempts + 1):
            req = request.model_copy(
                update={"attempt": attempt, "previous_error": errors[-1] if errors else None}
            )
            try:
                raw = await self._provider.extract(req)
                provider_name, model = raw.provider, raw.model
                result = self._validate(pack, request, raw.output)
                return result.model_copy(
                    update={
                        "provider": raw.provider,
                        "model": raw.model,
                        "attempts": attempt,
                        "errors": errors,
                    }
                )
            except (ValidationError, ValueError, AIProviderError) as exc:
                message = _summarise(exc)
                errors.append(f"attempt {attempt}: {message}")
                log.warning(
                    "extraction.invalid", attempt=attempt, error=message, provider=provider_name
                )
        return ExtractionResult(
            provider=provider_name, model=model, attempts=self._max_attempts, errors=errors
        )

    @staticmethod
    def _validate(
        pack: DomainPack, request: ExtractionRequest, output: dict[str, Any]
    ) -> ExtractionResult:
        envelope = _Envelope.model_validate(output)
        observations: list[ExtractedObservation] = []
        for item in envelope.new_observations:
            schema = pack.observation_schemas.get(item.observation_type)
            if schema is None:
                raise ValueError(f"unknown observation_type '{item.observation_type}'")
            validated = validate_fields(schema, item.fields)
            full = {name: validated.get(name) for name in schema.fields}
            observations.append(
                ExtractedObservation(
                    observation_type=schema.observation_type,
                    observation_schema_version=schema.version,
                    fields=full,
                    confidence=item.confidence,
                )
            )

        answer: ExtractedAnswer | None = None
        if envelope.answer is not None:
            pending = request.pending_question
            if pending is None or envelope.answer.field != pending.field:
                raise ValueError("answer does not correspond to the pending question")
            schema = pack.observation_schemas[pending.observation_type]
            value = None
            if not envelope.answer.declined:
                if envelope.answer.value is None:
                    raise ValueError("answer has no value and is not declined")
                value = validate_field_value(schema, pending.field, envelope.answer.value)
            answer = ExtractedAnswer(
                field=pending.field, value=value, declined=envelope.answer.declined
            )

        return ExtractionResult(
            new_observations=observations, answer=answer, provider="", model="", attempts=0
        )


def _summarise(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
    return str(exc)[:500]
