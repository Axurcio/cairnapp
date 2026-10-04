"""End-to-end message flow through the real API (SQLite + MockAIProvider)."""

from __future__ import annotations

import httpx

from cairn.container import Container
from cairn.context.provider import ContextScope
from tests.conftest import World


async def _send(client: httpx.AsyncClient, world: World, text: str) -> dict:  # type: ignore[type-arg]
    response = await client.post(
        f"/v1/journeys/{world.journey_id}/messages",
        json={"text": text},
        headers=world.participant_headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]


async def test_ready_reports_components(client: httpx.AsyncClient) -> None:
    body = (await client.get("/ready")).json()
    assert body["status"] == "ready"
    assert body["checks"]["ai_provider"]["provider"] == "mock"
    assert set(body["checks"]["domain_packs"]["loaded"]) == {
        "demo@1.0.0",
        "mentorship@0.1.0",
        "parkinsons@0.1.0",
    }


async def test_h_health_flow_returns_typed_response_and_progresses(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("parkinsons")

    first = await _send(client, world, "My right hand has been shaky lately.")
    assert first["response"]["text"] == (
        "Thanks for telling me. How long have you noticed the shaking in your right hand?"
    )
    assert first["next_action"]["action_type"] == "ASK_QUESTION"
    assert first["next_action"]["question_id"] == "hand_shaking.duration"
    assert first["next_action"]["policy_id"] == "hand_shaking_followup"
    assert first["next_action"]["policy_version"] == "1.0.0"
    assert first["next_action"]["domain_pack_version"] == "0.1.0"
    obs = first["observation"]
    assert obs["observation_type"] == "hand_shaking"
    assert obs["fields"] == {
        "body_location": "hand",
        "side": "right",
        "onset_side": None,
        "duration": None,
        "severity": None,
        "frequency": None,
        "activity_context": None,
        "functional_impact": None,
    }
    explanation = first["explanation"]
    assert explanation["policy_decision"]["reason"] == "required field duration is missing"
    assert explanation["intent"]["semantic_intent"] == (
        "Ask how long the participant has noticed the hand shaking."
    )
    assert "diagnosis" in explanation["intent"]["prohibited_topics"]
    assert explanation["extraction"]["provider"] == "mock"

    second = await _send(client, world, "About three months.")
    assert second["observation"]["id"] == obs["id"]
    assert second["observation"]["fields"]["duration"] == "P3M"
    assert second["next_action"]["question_id"] == "hand_shaking.severity"
    assert second["response"]["text"] == (
        "On a scale from 0 to 10, how noticeable would you say it is?"
    )

    for text in ("Maybe a 4", "Most days", "Mostly when I'm holding a cup"):
        await _send(client, world, text)
    final = await _send(client, world, "Writing takes a bit longer")
    assert final["observation"]["status"] == "complete"
    assert final["next_action"]["action_type"] == "ACKNOWLEDGE"
    assert final["response"]["text"] == (
        "Thank you - I've noted all of that. It may be useful to note when the shaking "
        "occurs and what you were doing at the time."
    )
    assert final["explanation"]["safety"]["output_violations"] == []


async def test_i_observation_has_source_event_provenance(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("parkinsons")
    first = await _send(client, world, "My right hand has been shaky lately.")
    second = await _send(client, world, "About three months.")
    obs = second["observation"]
    assert obs["source_event_ids"] == [
        first["participant_event_id"],
        second["participant_event_id"],
    ]
    assert obs["field_provenance"]["side"]["event_id"] == first["participant_event_id"]
    assert obs["field_provenance"]["duration"]["event_id"] == second["participant_event_id"]
    assert obs["field_provenance"]["duration"]["extractor"].startswith("mock:")
    assert obs["extraction_version"] == "1.0.0"

    timeline = (
        await client.get(
            f"/v1/journeys/{world.journey_id}/timeline", headers=world.participant_headers()
        )
    ).json()
    assert [e["event_type"] for e in timeline] == [
        "participant.message",
        "assistant.message",
        "participant.message",
        "assistant.message",
    ]
    assert timeline[1]["details"]["in_reply_to"] == first["participant_event_id"]


async def test_mentorship_uses_same_engine(client: httpx.AsyncClient, world_factory) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("mentorship")
    body = await _send(client, world, "I keep getting overlooked when projects are assigned.")
    fields = body["observation"]["fields"]
    assert (fields["topic"], fields["issue"], fields["goal"], fields["recent_example"]) == (
        "leadership",
        "project_opportunity",
        "greater_responsibility",
        None,
    )
    assert body["next_action"]["question_id"] == "recent_project_example"
    assert body["response"]["text"] == (
        "Can you think of the most recent project you wanted "
        "to lead but weren't given the opportunity?"
    )
    assert body["pattern_evaluations"][0]["rule_id"] == "repeated_project_opportunity_blocker"
    assert body["pattern_evaluations"][0]["matched"] is False


async def test_mentorship_harassment_is_signposted_not_coached(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("mentorship")
    body = await _send(client, world, "My manager harassed me after I was passed over.")
    assert body["next_action"]["action_type"] == "ESCALATE"
    assert body["explanation"]["policy_decision"]["action"] == "BLOCKED"
    assert "HR team" in body["response"]["text"]


async def test_escalation_trigger_skips_extraction(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("parkinsons")
    body = await _send(client, world, "My hand was shaking and I fell over yesterday.")
    assert body["next_action"]["action_type"] == "ESCALATE"
    assert body["explanation"]["extraction"] is None
    assert body["explanation"]["safety"]["input_signal"] == "fall_or_injury"
    assert "care team" in body["response"]["text"]


async def test_context_projection_is_derived_and_rebuildable(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("parkinsons")
    first = await _send(client, world, "My right hand has been shaky lately.")
    assert first["explanation"]["context"]["projection"] == "completed:2"
    scope = ContextScope(tenant_id=world.tenant_id, journey_id=world.journey_id)
    recalled = await container.context.recall(scope, "shaky hand")
    assert recalled
    assert str(recalled[0].source_event_ids[0]) == first["participant_event_id"]

    await container.context.forget_journey(world.tenant_id, world.journey_id)
    assert await container.context.recall(scope, "shaky hand") == []
    rebuilt = await client.post(
        f"/v1/journeys/{world.journey_id}/context/rebuild", headers=world.admin_headers()
    )
    assert rebuilt.status_code == 202
    assert await container.context.recall(scope, "shaky hand")


async def test_message_requires_conversation_consent(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("demo", consents=[])
    response = await client.post(
        f"/v1/journeys/{world.journey_id}/messages",
        json={"text": "I read a book"},
        headers=world.participant_headers(),
    )
    assert response.status_code == 403


async def test_projection_skipped_without_projection_consent(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    from cairn.domain.enums import ConsentScope

    world: World = await world_factory("demo", consents=[ConsentScope.CONVERSATION])
    body = await _send(client, world, "I read a novel this evening")
    assert body["explanation"]["context"]["projection"] == "skipped:no_consent"


async def test_report_is_descriptive_and_traceable(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("parkinsons")
    first = await _send(client, world, "My right hand has been shaky lately.")
    await _send(client, world, "About three months.")
    report = (
        await client.get(
            f"/v1/journeys/{world.journey_id}/report", headers=world.participant_headers()
        )
    ).json()
    assert "not a diagnosis" in report["disclaimer"]
    statement = report["sections"][0]["statements"][0]
    assert "Noticed for: 3 months" in statement["text"]
    assert first["participant_event_id"] in statement["source_event_ids"]


async def test_unknown_and_invalid_requests(client: httpx.AsyncClient, world_factory) -> None:  # type: ignore[no-untyped-def]
    world: World = await world_factory("demo")
    assert (
        await client.post(
            f"/v1/journeys/{world.journey_id}/messages",
            json={"text": ""},
            headers=world.participant_headers(),
        )
    ).status_code == 422
    assert (await client.get(f"/v1/journeys/{world.journey_id}")).status_code == 401
