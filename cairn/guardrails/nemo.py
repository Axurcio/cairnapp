"""NeMo Guardrails adapter (optional; ``uv sync --extra nemo``).

Uses ``LLMRails.check_async`` to run input/output rails against text Cairn has
already produced. The shipped config (``nemo_config/``) uses deterministic
custom-action rails, so it runs without any LLM; LLM self-check rails can be
enabled in the same config when a model is configured.

Any rail outcome other than PASSED is treated as "not allowed": Cairn never adopts
rail-modified text, it falls back to its own approved deterministic wording.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cairn.guardrails.provider import GuardrailCheck, GuardrailContext, GuardrailStage
from cairn.observability.logging import get_logger
from cairn.planner.intents import ResponseIntent

log = get_logger(__name__)


class NeMoGuardrailProvider:
    name = "nemo"

    def __init__(self, rails: Any) -> None:
        """``rails`` is an ``LLMRails`` instance (or a test double with ``check_async``)."""
        self._rails = rails

    @classmethod
    def from_config_path(cls, path: Path) -> NeMoGuardrailProvider:
        try:
            from nemoguardrails import LLMRails, RailsConfig
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "CAIRN_GUARDRAIL_PROVIDER=nemo requires the optional extra: uv sync --extra nemo"
            ) from exc
        return cls(LLMRails(RailsConfig.from_path(str(path))))

    async def _check(
        self, stage: GuardrailStage, messages: list[dict[str, Any]], rail_type: str
    ) -> GuardrailCheck:
        rail_types = self._rail_types(rail_type)
        try:
            result = await self._rails.check_async(messages, rail_types=rail_types)
        except Exception as exc:
            # Fail closed: an erroring guardrail forces the conservative path.
            log.warning("guardrail.error", stage=stage.value, error=type(exc).__name__)
            return GuardrailCheck(
                stage=stage,
                allowed=False,
                provider=self.name,
                reasons=[f"guardrail error: {type(exc).__name__}"],
            )
        status = str(getattr(result.status, "value", result.status)).lower()
        allowed = status == "passed"
        reasons = [] if allowed else [f"{status}: {getattr(result, 'rail', None) or 'rail'}"]
        return GuardrailCheck(stage=stage, allowed=allowed, provider=self.name, reasons=reasons)

    @staticmethod
    def _rail_types(rail_type: str) -> list[Any] | None:
        try:
            from nemoguardrails.rails.llm.options import RailType
        except ImportError:
            return None  # test doubles
        return [RailType(rail_type)]

    async def validate_input(self, text: str, ctx: GuardrailContext) -> GuardrailCheck:
        return await self._check(GuardrailStage.INPUT, [{"role": "user", "content": text}], "input")

    async def validate_context(self, snippets: list[str], ctx: GuardrailContext) -> GuardrailCheck:
        if not snippets:
            return GuardrailCheck(stage=GuardrailStage.CONTEXT, allowed=True, provider=self.name)
        # Recalled context is untrusted text; screen it like participant input.
        return await self._check(
            GuardrailStage.CONTEXT, [{"role": "user", "content": "\n".join(snippets)}], "input"
        )

    async def validate_tool_call(
        self, tool_name: str, arguments: dict[str, Any], ctx: GuardrailContext
    ) -> GuardrailCheck:
        # Cairn does not let LLMs call tools today; any attempt is refused.
        return GuardrailCheck(
            stage=GuardrailStage.TOOL_CALL,
            allowed=False,
            provider=self.name,
            reasons=[f"LLM tool calls are not permitted ({tool_name})"],
        )

    async def validate_output(
        self, text: str, intent: ResponseIntent, ctx: GuardrailContext
    ) -> GuardrailCheck:
        brief = json.dumps(
            {
                "semantic_intent": intent.semantic_intent,
                "prohibited_topics": intent.prohibited_topics,
            }
        )
        messages = [
            {"role": "user", "content": f"[Cairn response intent] {brief}"},
            {"role": "assistant", "content": text},
        ]
        return await self._check(GuardrailStage.OUTPUT, messages, "output")
