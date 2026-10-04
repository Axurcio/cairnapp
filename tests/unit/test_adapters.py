"""Vendor adapter boundaries (Graphiti, NeMo), tested with doubles - no Neo4j or NeMo needed."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from cairn.context.graphiti import GraphitiContextProvider, group_id_for
from cairn.context.provider import ContextEvent, ContextItemKind, ContextScope, context_item_id
from cairn.domain.enums import NextActionType
from cairn.guardrails.nemo import NeMoGuardrailProvider
from cairn.guardrails.provider import GuardrailContext
from cairn.planner.intents import ResponseIntent

graphiti_core = pytest.importorskip("graphiti_core")

SCOPE = ContextScope(tenant_id=uuid4(), journey_id=uuid4())


def _event(text: str = "My right hand has been shaky") -> ContextEvent:
    return ContextEvent(
        scope=SCOPE,
        source_event_id=uuid4(),
        kind=ContextItemKind.PARTICIPANT_MESSAGE,
        text=text,
        occurred_at=datetime.now(UTC),
        domain_pack="parkinsons",
    )


def _graphiti() -> MagicMock:
    client = MagicMock()
    client.driver = MagicMock()
    client.retrieve_episodes = AsyncMock(return_value=[])
    client.add_episode = AsyncMock()
    client.remove_episode = AsyncMock()
    client.search = AsyncMock(return_value=[])
    return client


def test_g_group_id_is_valid_graphiti_partition() -> None:
    from graphiti_core.helpers import validate_group_id

    gid = group_id_for(SCOPE.tenant_id, SCOPE.journey_id)
    assert validate_group_id(gid)
    assert SCOPE.tenant_id.hex in gid
    assert SCOPE.journey_id.hex in gid


async def test_g_episodes_mode_saves_episode_keyed_by_canonical_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[Any] = []

    async def fake_save(self: Any, driver: Any) -> None:
        saved.append(self)

    monkeypatch.setattr("graphiti_core.nodes.EpisodicNode.save", fake_save)
    client = _graphiti()
    event = _event()
    result = await GraphitiContextProvider(client, mode="episodes").retain_event(event)

    [episode] = saved
    assert episode.uuid == str(context_item_id(event.source_event_id, event.kind))
    assert episode.name == f"cairn:participant_message:{event.source_event_id}"
    assert episode.group_id == group_id_for(SCOPE.tenant_id, SCOPE.journey_id)
    assert result.item_id == episode.uuid
    client.add_episode.assert_not_awaited()  # no LLM call in episodes mode


async def test_g_full_mode_uses_add_episode_with_deterministic_uuid() -> None:
    client = _graphiti()
    event = _event()
    await GraphitiContextProvider(client, mode="full").retain_event(event)
    kwargs = client.add_episode.await_args.kwargs
    assert kwargs["uuid"] == str(event.item_id)
    assert kwargs["group_id"] == group_id_for(SCOPE.tenant_id, SCOPE.journey_id)


async def test_g_recall_maps_episodes_back_to_source_events() -> None:
    source = uuid4()
    episode = SimpleNamespace(
        uuid="ep-1",
        name=f"cairn:participant_message:{source}",
        content="right hand shaky when holding a cup",
        valid_at=datetime.now(UTC),
        group_id="g",
    )
    client = _graphiti()
    client.retrieve_episodes.return_value = [episode]
    items = await GraphitiContextProvider(client).recall(SCOPE, "shaky hand")
    assert items[0].source_event_ids == [source]
    assert client.retrieve_episodes.await_args.kwargs["group_ids"] == [
        group_id_for(SCOPE.tenant_id, SCOPE.journey_id)
    ]


async def test_g_forget_source_only_removes_items_in_callers_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = uuid4()
    own_group = group_id_for(SCOPE.tenant_id, SCOPE.journey_id)
    mine = SimpleNamespace(
        uuid=str(context_item_id(source, ContextItemKind.PARTICIPANT_MESSAGE)), group_id=own_group
    )
    foreign = SimpleNamespace(
        uuid=str(context_item_id(source, ContextItemKind.ASSISTANT_MESSAGE)),
        group_id="cairn_other_tenant",
    )
    requested: list[list[str]] = []

    async def fake_get_by_uuids(driver: Any, uuids: list[str]) -> list[Any]:
        requested.append(uuids)
        return [mine, foreign]

    monkeypatch.setattr("graphiti_core.nodes.EpisodicNode.get_by_uuids", fake_get_by_uuids)
    client = _graphiti()
    removed = await GraphitiContextProvider(client).forget_source(SCOPE, source)

    assert removed == 1
    client.remove_episode.assert_awaited_once_with(mine.uuid)
    assert set(requested[0]) == {str(context_item_id(source, k)) for k in ContextItemKind}


class FakeRails:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls: list[list[dict[str, Any]]] = []

    async def check_async(self, messages: list[dict[str, Any]], rail_types: Any = None) -> Any:
        self.calls.append(messages)
        return SimpleNamespace(status=self.status, rail="cairn check output", content="")


def _intent() -> ResponseIntent:
    return ResponseIntent(
        kind=NextActionType.ASK_QUESTION,
        semantic_intent="Ask duration",
        deterministic_text="How long?",
        prohibited_topics=["diagnosis"],
        domain_pack="parkinsons",
        domain_pack_version="0.1.0",
    )


CTX = GuardrailContext(domain_pack="parkinsons", domain_pack_version="0.1.0")


async def test_nemo_output_blocked_is_not_allowed() -> None:
    rails = FakeRails("blocked")
    check = await NeMoGuardrailProvider(rails).validate_output("You have X.", _intent(), CTX)
    assert not check.allowed
    assert check.provider == "nemo"
    # The ResponseIntent is supplied to NeMo so it can check grounding.
    assert "Ask duration" in rails.calls[0][0]["content"]


async def test_nemo_modified_output_is_treated_as_not_allowed() -> None:
    check = await NeMoGuardrailProvider(FakeRails("modified")).validate_input("hi", CTX)
    assert not check.allowed


async def test_nemo_passed() -> None:
    check = await NeMoGuardrailProvider(FakeRails("passed")).validate_input("hi", CTX)
    assert check.allowed


async def test_nemo_errors_fail_closed() -> None:
    rails = MagicMock()
    rails.check_async = AsyncMock(side_effect=RuntimeError("boom"))
    check = await NeMoGuardrailProvider(rails).validate_output("x", _intent(), CTX)
    assert not check.allowed


async def test_nemo_refuses_llm_tool_calls() -> None:
    check = await NeMoGuardrailProvider(FakeRails("passed")).validate_tool_call("sql", {}, CTX)
    assert not check.allowed


def test_real_nemo_config_when_extra_installed() -> None:
    pytest.importorskip("nemoguardrails")
    from cairn.config.settings import CairnSettings

    provider = NeMoGuardrailProvider.from_config_path(CairnSettings().nemo_config_path)
    assert provider.name == "nemo"
