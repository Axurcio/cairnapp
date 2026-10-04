"""In-process ContextMemoryProvider for tests and credential-free local use.

Recall uses simple token-overlap scoring. Data lives only in this process; since
context is a derived projection, it can be rebuilt from Postgres at any time.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from cairn.context.provider import (
    ContextEvent,
    ContextItem,
    ContextItemKind,
    ContextScope,
    ProviderHealth,
    RebuildResult,
    RetainResult,
    SourceRef,
    context_item_id,
)

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "i",
        "my",
        "is",
        "it",
        "to",
        "of",
        "in",
        "has",
        "have",
        "been",
        "when",
        "was",
        "be",
        "on",
        "for",
        "me",
    }
)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


class InMemoryContextProvider:
    name = "in_memory"

    def __init__(self) -> None:
        # (tenant_id, journey_id) -> item_id -> event
        self._items: dict[tuple[UUID, UUID], dict[str, ContextEvent]] = {}

    def _bucket(self, tenant_id: UUID, journey_id: UUID) -> dict[str, ContextEvent]:
        return self._items.setdefault((tenant_id, journey_id), {})

    @staticmethod
    def _to_item(event: ContextEvent, score: float | None = None) -> ContextItem:
        return ContextItem(
            item_id=str(event.item_id),
            text=event.text,
            kind=event.kind.value,
            occurred_at=event.occurred_at,
            score=score,
            source_event_ids=[event.source_event_id],
            provider=InMemoryContextProvider.name,
        )

    async def initialize(self) -> None:
        return None

    async def retain_event(self, event: ContextEvent) -> RetainResult:
        bucket = self._bucket(event.scope.tenant_id, event.scope.journey_id)
        key = str(event.item_id)
        created = key not in bucket
        bucket[key] = event
        return RetainResult(item_id=key, provider=self.name, created=created)

    async def recall(self, scope: ContextScope, query: str, *, limit: int = 5) -> list[ContextItem]:
        wanted = _tokens(query)
        scored: list[tuple[float, ContextEvent]] = []
        for event in self._bucket(scope.tenant_id, scope.journey_id).values():
            overlap = len(wanted & _tokens(event.text))
            if overlap:
                scored.append((overlap / max(len(wanted), 1), event))
        scored.sort(key=lambda s: (s[0], s[1].occurred_at), reverse=True)
        return [self._to_item(e, round(score, 3)) for score, e in scored[:limit]]

    async def get_temporal_context(
        self, scope: ContextScope, *, start: datetime, end: datetime, limit: int = 50
    ) -> list[ContextItem]:
        events = [
            e
            for e in self._bucket(scope.tenant_id, scope.journey_id).values()
            if start <= e.occurred_at <= end
        ]
        events.sort(key=lambda e: e.occurred_at)
        return [self._to_item(e) for e in events[:limit]]

    async def get_participant_context(
        self,
        tenant_id: UUID,
        participant_id: UUID,
        journey_ids: Sequence[UUID],
        *,
        limit: int = 20,
    ) -> list[ContextItem]:
        events = [
            e
            for jid in journey_ids
            for e in self._bucket(tenant_id, jid).values()
            if e.scope.participant_id in (None, participant_id)
        ]
        events.sort(key=lambda e: e.occurred_at, reverse=True)
        return [self._to_item(e) for e in events[:limit]]

    async def get_evidence_sources(
        self, scope: ContextScope, item_ids: Sequence[str]
    ) -> list[SourceRef]:
        bucket = self._bucket(scope.tenant_id, scope.journey_id)
        return [
            SourceRef(item_id=i, source_event_ids=[bucket[i].source_event_id])
            for i in item_ids
            if i in bucket
        ]

    async def forget_source(self, scope: ContextScope, source_event_id: UUID) -> int:
        bucket = self._bucket(scope.tenant_id, scope.journey_id)
        removed = 0
        for kind in ContextItemKind:
            if bucket.pop(str(context_item_id(source_event_id, kind)), None) is not None:
                removed += 1
        return removed

    async def forget_journey(self, tenant_id: UUID, journey_id: UUID) -> int:
        return len(self._items.pop((tenant_id, journey_id), {}))

    async def rebuild_journey(
        self, scope: ContextScope, events: Sequence[ContextEvent]
    ) -> RebuildResult:
        removed = await self.forget_journey(scope.tenant_id, scope.journey_id)
        for event in events:
            await self.retain_event(event)
        return RebuildResult(provider=self.name, removed=removed, retained=len(events))

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, healthy=True)

    async def aclose(self) -> None:
        return None
