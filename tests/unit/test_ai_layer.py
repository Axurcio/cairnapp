"""AI gateway: mock extraction, validation with bounded retry, renderers, providers."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from cairn.ai.answer_parsing import DECLINED, parse_answer
from cairn.ai.extraction import ExtractionService
from cairn.ai.mock import MockAIProvider
from cairn.ai.openai_compatible import OpenAICompatibleProvider
from cairn.ai.provider import AIResponse, ExtractionRequest, PendingQuestionContext, RawExtraction
from cairn.ai.rendering import DeterministicTemplateRenderer, LLMResponseRenderer
from cairn.domain.enums import NextActionType
from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.schemas import FieldSpec, FieldType
from cairn.planner.intents import GuidanceRef, ResponseIntent


def _request(
    pack: DomainPack, message: str, pending: PendingQuestionContext | None = None
) -> ExtractionRequest:
    return ExtractionRequest(
        message=message,
        domain_pack=pack.id,
        domain_pack_version=pack.version,
        observation_schemas=list(pack.observation_schemas.values()),
        pending_question=pending,
    )


async def test_mock_extraction_matches_spec_example(parkinsons: DomainPack) -> None:
    result = await ExtractionService(MockAIProvider()).extract(
        parkinsons, _request(parkinsons, "My right hand has been shaky lately.")
    )
    [obs] = result.new_observations
    assert obs.observation_type == "hand_shaking"
    assert obs.fields["body_location"] == "hand"
    assert obs.fields["side"] == "right"
    assert all(
        obs.fields[f] is None
        for f in ("duration", "severity", "frequency", "activity_context", "functional_impact")
    )
    assert result.errors == []


async def test_mock_extraction_answers_pending_question(parkinsons: DomainPack) -> None:
    schema = parkinsons.observation_schemas["hand_shaking"]
    pending = PendingQuestionContext(
        question_id="hand_shaking.duration",
        observation_type="hand_shaking",
        field="duration",
        field_spec=schema.fields["duration"],
        intent="duration",
    )
    result = await ExtractionService(MockAIProvider()).extract(
        parkinsons, _request(parkinsons, "About three months.", pending)
    )
    assert result.answer is not None
    assert (result.answer.field, result.answer.value) == ("duration", "P3M")


class ScriptedProvider:
    """Returns pre-baked raw outputs, one per call."""

    name = "scripted"

    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = outputs
        self.requests: list[ExtractionRequest] = []

    async def extract(self, request: ExtractionRequest) -> RawExtraction:
        self.requests.append(request)
        return RawExtraction(output=self.outputs.pop(0), provider=self.name, model="m")

    async def render_response(self, intent: ResponseIntent) -> AIResponse:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


async def test_invalid_output_is_retried_then_accepted(parkinsons: DomainPack) -> None:
    bad = {"new_observations": [{"observation_type": "hand_shaking", "fields": {"severity": 99}}]}
    good = {"new_observations": [{"observation_type": "hand_shaking", "fields": {"severity": 4}}]}
    provider = ScriptedProvider([bad, good])
    result = await ExtractionService(provider, max_attempts=2).extract(
        parkinsons, _request(parkinsons, "x")
    )
    assert result.new_observations[0].fields["severity"] == 4
    assert result.attempts == 2
    assert len(result.errors) == 1
    assert provider.requests[1].previous_error is not None


async def test_invalid_output_never_coerced_after_bounded_retries(parkinsons: DomainPack) -> None:
    outputs = [
        {
            "new_observations": [
                {"observation_type": "hand_shaking", "fields": {"diagnosis": "parkinsons"}}
            ]
        },  # unknown field
        {"new_observations": [{"observation_type": "made_up", "fields": {}}]},  # unknown type
        {
            "new_observations": [
                {"observation_type": "hand_shaking", "fields": {"side": "upside-down"}}
            ]
        },  # bad enum
    ]
    result = await ExtractionService(ScriptedProvider(outputs), max_attempts=3).extract(
        parkinsons, _request(parkinsons, "x")
    )
    assert result.failed
    assert result.new_observations == []
    assert len(result.errors) == 3


async def test_answer_for_wrong_field_rejected(parkinsons: DomainPack) -> None:
    schema = parkinsons.observation_schemas["hand_shaking"]
    pending = PendingQuestionContext(
        question_id="hand_shaking.duration",
        observation_type="hand_shaking",
        field="duration",
        field_spec=schema.fields["duration"],
        intent="duration",
    )
    provider = ScriptedProvider([{"answer": {"field": "severity", "value": 3}}])
    result = await ExtractionService(provider, max_attempts=1).extract(
        parkinsons, _request(parkinsons, "x", pending)
    )
    assert result.failed


@pytest.mark.parametrize(
    ("text", "spec", "expected"),
    [
        ("About three months.", FieldSpec(type=FieldType.DURATION), "P3M"),
        ("a few weeks", FieldSpec(type=FieldType.DURATION), "P3W"),
        ("2 years", FieldSpec(type=FieldType.DURATION), "P2Y"),
        ("Maybe a 4", FieldSpec(type=FieldType.INTEGER, minimum=0, maximum=10), 4),
        ("7/10", FieldSpec(type=FieldType.INTEGER, minimum=0, maximum=10), 7),
        ("eleven", FieldSpec(type=FieldType.INTEGER, minimum=0, maximum=10), None),
        (
            "most days",
            FieldSpec(
                type=FieldType.ENUM,
                values=["occasionally", "daily"],
                synonyms={"daily": ["most days"]},
            ),
            "daily",
        ),
        ("yes", FieldSpec(type=FieldType.BOOLEAN), True),
        ("I'd rather not say", FieldSpec(type=FieldType.INTEGER), DECLINED),
        ("hmm", FieldSpec(type=FieldType.DURATION), None),
    ],
)
def test_answer_parsing(text: str, spec: FieldSpec, expected: object) -> None:
    assert parse_answer(text, spec) == expected


def _intent(**overrides: Any) -> ResponseIntent:
    base: dict[str, Any] = dict(
        kind=NextActionType.ASK_QUESTION,
        semantic_intent="Ask duration",
        deterministic_text="How long have you noticed it?",
        preamble="Thanks for telling me.",
        allow_llm_variation=True,
        max_sentences=2,
        domain_pack="parkinsons",
        domain_pack_version="0.1.0",
        guidance=[GuidanceRef(id="g", version="1.0.0", category="c", text="Approved text.")],
    )
    base.update(overrides)
    return ResponseIntent(**base)


class FixedRenderProvider(ScriptedProvider):
    def __init__(self, text: str) -> None:
        super().__init__([])
        self.text = text

    async def render_response(self, intent: ResponseIntent) -> AIResponse:
        return AIResponse(text=self.text, provider="fixed", model="m")


async def test_template_renderer_is_verbatim() -> None:
    rendered = await DeterministicTemplateRenderer().render(_intent())
    assert rendered.text == "Thanks for telling me. How long have you noticed it? Approved text."


async def test_llm_renderer_appends_guidance_verbatim() -> None:
    rendered = await LLMResponseRenderer(
        FixedRenderProvider("Thank you. Since when have you noticed it?")
    ).render(_intent())
    assert rendered.renderer == "llm"
    assert rendered.text.endswith("Approved text.")


@pytest.mark.parametrize(
    ("llm_text", "overrides"),
    [
        ("One. Two. Three. Four?", {}),  # exceeds sentence budget
        ("Thanks for sharing.", {}),  # a question intent rendered without a question
        ("Sure?", {"allow_llm_variation": False}),  # policy forbids variation
    ],
)
async def test_llm_renderer_falls_back_to_template(
    llm_text: str, overrides: dict[str, Any]
) -> None:
    rendered = await LLMResponseRenderer(FixedRenderProvider(llm_text)).render(_intent(**overrides))
    assert rendered.renderer == "template"
    assert rendered.fallback_reason


async def test_openai_compatible_provider_uses_chat_completions() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        content = json.dumps({"new_observations": [], "answer": None})
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="http://llm.local/v1",
        api_key="k",
        model="m",
        transport=httpx.MockTransport(handler),
    )
    raw = await provider.extract(
        ExtractionRequest(
            message="hi", domain_pack="demo", domain_pack_version="1.0.0", observation_schemas=[]
        )
    )
    await provider.aclose()
    assert raw.output == {"new_observations": [], "answer": None}
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert seen[0]["temperature"] == 0
