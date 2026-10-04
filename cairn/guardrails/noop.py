"""Pass-through guardrails for local development and tests.

Safe as a default because Cairn's deterministic SafetyPolicy still validates every
decision, intent and rendered output.
"""

from __future__ import annotations

from typing import Any

from cairn.guardrails.provider import GuardrailCheck, GuardrailContext, GuardrailStage
from cairn.planner.intents import ResponseIntent


class NoOpGuardrailProvider:
    name = "noop"

    def _ok(self, stage: GuardrailStage) -> GuardrailCheck:
        return GuardrailCheck(stage=stage, allowed=True, provider=self.name)

    async def validate_input(self, text: str, ctx: GuardrailContext) -> GuardrailCheck:
        return self._ok(GuardrailStage.INPUT)

    async def validate_context(self, snippets: list[str], ctx: GuardrailContext) -> GuardrailCheck:
        return self._ok(GuardrailStage.CONTEXT)

    async def validate_tool_call(
        self, tool_name: str, arguments: dict[str, Any], ctx: GuardrailContext
    ) -> GuardrailCheck:
        return self._ok(GuardrailStage.TOOL_CALL)

    async def validate_output(
        self, text: str, intent: ResponseIntent, ctx: GuardrailContext
    ) -> GuardrailCheck:
        return self._ok(GuardrailStage.OUTPUT)
