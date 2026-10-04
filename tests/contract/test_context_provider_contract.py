"""Contract every ContextMemoryProvider must satisfy (test F).

Runs against InMemoryContextProvider always, and against GraphitiContextProvider
(episodes mode, real Neo4j) when ``CAIRN_INTEGRATION=1`` (``make integration``). Any future
provider (e.g. Hindsight) must pass the same suite.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from cairn.context.in_memory import InMemoryContextProvider
from cairn.context.provider import (
    ContextEvent,
    ContextItemKind,
    ContextMemoryProvider,
    ContextScope,
)

NOW = datetime.now(UTC).replace(microsecond=0)


async def _graphiti() -> ContextMemoryProvider:
    if os.environ.get("CAIRN_INTEGRATION") != "1":
        pytest.skip("set CAIRN_INTEGRATION=1 (make integration) to run against Neo4j")
    from cairn.context.graphiti import GraphitiContextProvider, create_graphiti_client

    client = create_graphiti_client(
        uri=os.environ.get("CAIRN_NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("CAIRN_NEO4J_USER", "neo4j"),
        password=os.environ.get("CAIRN_NEO4J_PASSWORD", "cairn_local_dev_only"),
        mode="episodes",
        llm_api_key=None,
        llm_base_url=None,
        llm_model=None,
    )
    provider = GraphitiContextProvider(client, mode="episodes")
    try:
        await provider.initialize()
    except Exception as exc:
        await provider.aclose()
        pytest.skip(f"Neo4j not reachable for Graphiti contract tests: {type(exc).__name__}")
    return provider


@pytest.fixture(params=["in_memory", pytest.param("graphiti", marks=pytest.mark.integration)])
async def provider(request: pytest.FixtureRequest) -> AsyncIterator[ContextMemoryProvider]:
    if request.param == "in_memory":
        p: ContextMemoryProvider = InMemoryContextProvider()
    else:
        p = await _graphiti()
    yield p
    await p.aclose()


def _scope() -> ContextScope:
    return ContextScope(tenant_id=uuid4(), journey_id=uuid4(), participant_id=uuid4())


def _event(
    scope: ContextScope,
    text: str,
    minutes_ago: int = 0,
    kind: ContextItemKind = ContextItemKind.PARTICIPANT_MESSAGE,
) -> ContextEvent:
    return ContextEvent(
        scope=scope,
        source_event_id=uuid4(),
        kind=kind,
        text=text,
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        domain_pack="demo",
    )


async def test_retain_and_recall_with_provenance(provider: ContextMemoryProvider) -> None:
    scope = _scope()
    event = _event(scope, "I read a poem about the sea")
    retained = await provider.retain_event(event)
    assert retained.item_id == str(event.item_id)
    items = await provider.recall(scope, "poem sea")
    assert [i.text for i in items] == ["I read a poem about the sea"]
    assert items[0].source_event_ids == [event.source_event_id]
    sources = await provider.get_evidence_sources(scope, [items[0].item_id])
    assert sources[0].source_event_ids == [event.source_event_id]


async def test_recall_is_partitioned_by_tenant_and_journey(provider: ContextMemoryProvider) -> None:
    a, b = _scope(), _scope()
    await provider.retain_event(_event(a, "secret garden novel"))
    assert await provider.recall(b, "secret garden novel") == []


async def test_temporal_context(provider: ContextMemoryProvider) -> None:
    scope = _scope()
    await provider.retain_event(_event(scope, "old entry", minutes_ago=120))
    await provider.retain_event(_event(scope, "recent entry", minutes_ago=5))
    items = await provider.get_temporal_context(scope, start=NOW - timedelta(minutes=30), end=NOW)
    assert [i.text for i in items] == ["recent entry"]


async def test_forget_source_removes_only_that_source(provider: ContextMemoryProvider) -> None:
    scope = _scope()
    keep, drop = _event(scope, "keep this book note"), _event(scope, "drop this book note")
    summary = ContextEvent(
        scope=scope,
        source_event_id=drop.source_event_id,
        kind=ContextItemKind.OBSERVATION_SUMMARY,
        text="book note summary",
        occurred_at=NOW,
        domain_pack="demo",
    )
    for e in (keep, drop, summary):
        await provider.retain_event(e)
    assert await provider.forget_source(scope, drop.source_event_id) == 2
    texts = {i.text for i in await provider.recall(scope, "book note")}
    assert texts == {"keep this book note"}


async def test_forget_journey_then_rebuild(provider: ContextMemoryProvider) -> None:
    scope = _scope()
    events = [_event(scope, f"chapter {n} of the novel", minutes_ago=n) for n in range(3)]
    for e in events:
        await provider.retain_event(e)
    assert await provider.forget_journey(scope.tenant_id, scope.journey_id) >= 3
    assert await provider.recall(scope, "novel chapter") == []

    result = await provider.rebuild_journey(scope, events)
    assert result.retained == 3
    assert len(await provider.recall(scope, "novel chapter", limit=10)) == 3


async def test_participant_context_spans_given_journeys(provider: ContextMemoryProvider) -> None:
    tenant, participant = uuid4(), uuid4()
    j1 = ContextScope(tenant_id=tenant, journey_id=uuid4(), participant_id=participant)
    j2 = ContextScope(tenant_id=tenant, journey_id=uuid4(), participant_id=participant)
    await provider.retain_event(_event(j1, "first journey note"))
    await provider.retain_event(_event(j2, "second journey note"))
    items = await provider.get_participant_context(
        tenant, participant, [j1.journey_id, j2.journey_id]
    )
    assert {i.text for i in items} == {"first journey note", "second journey note"}


async def test_health(provider: ContextMemoryProvider) -> None:
    assert (await provider.health()).healthy
