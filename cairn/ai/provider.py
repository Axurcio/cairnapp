"""Provider-neutral AI gateway contract.

Business logic depends only on :class:`AIProvider`. Providers do two narrow jobs:

* ``extract`` - turn participant language into *unvalidated* structured output
  (validated afterwards by :mod:`cairn.ai.extraction` against Domain Pack schemas)
* ``render_response`` - phrase an already-decided :class:`ResponseIntent`

Providers never choose actions, policies, questions or guidance.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from cairn.domain_packs.schemas import FieldSpec, ObservationSchema
from cairn.planner.intents import ResponseIntent


class PendingQuestionContext(BaseModel):
    question_id: str
    observation_type: str
    field: str
    field_spec: FieldSpec
    intent: str


class ExtractionRequest(BaseModel):
    message: str
    domain_pack: str
    domain_pack_version: str
    observation_schemas: list[ObservationSchema]
    pending_question: PendingQuestionContext | None = None
    context_snippets: list[str] = Field(default_factory=list)
    attempt: int = 1
    previous_error: str | None = None


class RawExtraction(BaseModel):
    """Unvalidated provider output. Expected JSON shape::

    {"new_observations": [{"observation_type": str, "fields": {...}, "confidence": float}],
     "answer": {"field": str, "value": any, "declined": bool} | null}
    """

    output: dict[str, Any]
    provider: str
    model: str


class AIResponse(BaseModel):
    text: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class AIProviderError(RuntimeError):
    pass


class AIProvider(Protocol):
    name: str

    async def extract(self, request: ExtractionRequest) -> RawExtraction: ...

    async def render_response(self, intent: ResponseIntent) -> AIResponse: ...

    async def aclose(self) -> None: ...
