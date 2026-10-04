"""GuardrailProvider: defence-in-depth around LLM interaction.

Guardrails are NOT the business policy engine. They never decide authentication,
tenant isolation, consent, authorization, data residency or application
permissions - those are enforced by Cairn code before any model is involved.
Cairn's SafetyPolicy remains authoritative; a guardrail can only make Cairn
*more* conservative (e.g. force the deterministic template).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from cairn.planner.intents import ResponseIntent


class GuardrailStage(StrEnum):
    INPUT = "input"
    CONTEXT = "context"
    TOOL_CALL = "tool_call"
    OUTPUT = "output"


class GuardrailContext(BaseModel):
    domain_pack: str
    domain_pack_version: str
    journey_id: str | None = None


class GuardrailCheck(BaseModel):
    stage: GuardrailStage
    allowed: bool
    provider: str
    reasons: list[str] = Field(default_factory=list)


class GuardrailProvider(Protocol):
    name: str

    async def validate_input(self, text: str, ctx: GuardrailContext) -> GuardrailCheck: ...

    async def validate_context(
        self, snippets: list[str], ctx: GuardrailContext
    ) -> GuardrailCheck: ...

    async def validate_tool_call(
        self, tool_name: str, arguments: dict[str, Any], ctx: GuardrailContext
    ) -> GuardrailCheck: ...

    async def validate_output(
        self, text: str, intent: ResponseIntent, ctx: GuardrailContext
    ) -> GuardrailCheck: ...
