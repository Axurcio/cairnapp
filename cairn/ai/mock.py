"""MockAIProvider: deterministic, offline, credential-free.

Extraction is driven entirely by Domain Pack data: each observation schema may
declare ``mock_extraction`` hints (trigger regexes and field regexes), and pending
question answers are parsed by field type. Rendering returns the intent's approved
deterministic wording. This is the default provider for local dev and all tests.
"""

from __future__ import annotations

import re
from typing import Any

from cairn.ai.answer_parsing import DECLINED, parse_answer
from cairn.ai.provider import AIResponse, ExtractionRequest, RawExtraction
from cairn.planner.intents import ResponseIntent


class MockAIProvider:
    name = "mock"
    model = "mock-deterministic-1"

    async def extract(self, request: ExtractionRequest) -> RawExtraction:
        text = request.message
        new_observations: list[dict[str, Any]] = []
        for schema in request.observation_schemas:
            hints = schema.mock_extraction
            if not hints:
                continue
            if not any(re.search(p, text, re.IGNORECASE) for p in hints.trigger_patterns):
                continue
            fields: dict[str, Any] = dict.fromkeys(schema.fields)
            fields.update(hints.defaults)
            for name, patterns in hints.field_patterns.items():
                for pattern in patterns:
                    if re.search(pattern.pattern, text, re.IGNORECASE):
                        fields[name] = pattern.value
                        break
            new_observations.append(
                {"observation_type": schema.observation_type, "fields": fields, "confidence": 0.9}
            )

        answer: dict[str, Any] | None = None
        pending = request.pending_question
        if pending and not new_observations:
            parsed = parse_answer(text, pending.field_spec)
            if parsed is DECLINED:
                answer = {"field": pending.field, "value": None, "declined": True}
            elif parsed is not None:
                answer = {"field": pending.field, "value": parsed, "declined": False}

        return RawExtraction(
            output={"new_observations": new_observations, "answer": answer},
            provider=self.name,
            model=self.model,
        )

    async def render_response(self, intent: ResponseIntent) -> AIResponse:
        parts = [intent.preamble, intent.deterministic_text]
        return AIResponse(
            text=" ".join(p for p in parts if p),
            provider=self.name,
            model=self.model,
            finish_reason="stop",
        )

    async def aclose(self) -> None:
        return None
