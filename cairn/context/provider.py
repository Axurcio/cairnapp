"""ContextMemoryProvider: the boundary for derived, AI-retrievable context.

Canonical Cairn data (PostgreSQL) describes what actually happened. Context
memory is a *derived, replaceable projection* of that data, optimised for
retrieval. Consequently:

* every :class:`ContextItem` references the canonical events it came from
* a projection can be dropped (``forget_*``) and rebuilt from canonical data
  (``rebuild_journey``) at any time without losing anything important
* providers are never used for authorization; callers resolve scope from
  canonical data first and pass explicit tenant/journey identifiers

The API and business layers depend only on this protocol, never on Graphiti.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

# Stable namespace so projection item ids are deterministic per (event, kind).
CONTEXT_ITEM_NAMESPACE = uuid.UUID("8f2c1a5e-4b6d-4e8f-9a1b-2c3d4e5f6a7b")


class ContextItemKind(StrEnum):
    PARTICIPANT_MESSAGE = "participant_message"
    ASSISTANT_MESSAGE = "assistant_message"
    OBSERVATION_SUMMARY = "observation_summary"
    EVIDENCE_NOTE = "evidence_note"


def context_item_id(source_event_id: UUID, kind: ContextItemKind) -> UUID:
    return uuid.uuid5(CONTEXT_ITEM_NAMESPACE, f"{source_event_id}:{kind.value}")


class ContextScope(BaseModel):
    tenant_id: UUID
    journey_id: UUID
    participant_id: UUID | None = None


class ContextEvent(BaseModel):
    """A canonical fact, rendered as text, to be retained in the projection."""

    scope: ContextScope
    source_event_id: UUID
    kind: ContextItemKind
    text: str
    occurred_at: datetime
    domain_pack: str
    source_evidence_ids: list[UUID] = Field(default_factory=list)

    @property
    def item_id(self) -> UUID:
        return context_item_id(self.source_event_id, self.kind)


class ContextItem(BaseModel):
    item_id: str
    text: str
    kind: str
    occurred_at: datetime | None
    score: float | None = None
    source_event_ids: list[UUID] = Field(default_factory=list)
    provider: str


class SourceRef(BaseModel):
    item_id: str
    source_event_ids: list[UUID]


class RetainResult(BaseModel):
    item_id: str
    provider: str
    created: bool


class RebuildResult(BaseModel):
    provider: str
    removed: int
    retained: int


class ProviderHealth(BaseModel):
    provider: str
    healthy: bool
    detail: str | None = None


class ContextMemoryProvider(Protocol):
    name: str

    async def initialize(self) -> None: ...

    async def retain_event(self, event: ContextEvent) -> RetainResult: ...

    async def recall(
        self, scope: ContextScope, query: str, *, limit: int = 5
    ) -> list[ContextItem]: ...

    async def get_temporal_context(
        self, scope: ContextScope, *, start: datetime, end: datetime, limit: int = 50
    ) -> list[ContextItem]: ...

    async def get_participant_context(
        self,
        tenant_id: UUID,
        participant_id: UUID,
        journey_ids: Sequence[UUID],
        *,
        limit: int = 20,
    ) -> list[ContextItem]: ...

    async def get_evidence_sources(
        self, scope: ContextScope, item_ids: Sequence[str]
    ) -> list[SourceRef]: ...

    async def forget_source(self, scope: ContextScope, source_event_id: UUID) -> int: ...

    async def forget_journey(self, tenant_id: UUID, journey_id: UUID) -> int: ...

    async def rebuild_journey(
        self, scope: ContextScope, events: Sequence[ContextEvent]
    ) -> RebuildResult: ...

    async def health(self) -> ProviderHealth: ...

    async def aclose(self) -> None: ...
