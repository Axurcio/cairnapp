"""Project canonical Postgres data into the derived context memory.

This is the only writer to a ContextMemoryProvider. It always reads from the
canonical store first (by id, tenant-scoped), checks consent, and renders text
that references the source events. Because of that, ``rebuild_journey`` can
reconstruct the projection from scratch at any time.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cairn.context.provider import (
    ContextEvent,
    ContextItemKind,
    ContextMemoryProvider,
    ContextScope,
    RebuildResult,
)
from cairn.domain.enums import ConsentScope, EventType, JourneyStatus
from cairn.domain.models import Journey, Observation, ParticipantEvent
from cairn.domain_packs.registry import DomainPackRegistry
from cairn.observability.logging import get_logger
from cairn.persistence.repositories import Repositories

log = get_logger(__name__)

_EVENT_KIND = {
    EventType.PARTICIPANT_MESSAGE: ContextItemKind.PARTICIPANT_MESSAGE,
    EventType.ASSISTANT_MESSAGE: ContextItemKind.ASSISTANT_MESSAGE,
    EventType.EVIDENCE_ADDED: ContextItemKind.EVIDENCE_NOTE,
}


class ProjectionOutcome(BaseModel):
    retained: int
    skipped_reason: str | None = None


def observation_facts(observations: Sequence[Observation], event_id: UUID) -> list[str]:
    """Facts that a specific event contributed (temporally accurate)."""
    facts: list[str] = []
    for obs in observations:
        supplied = [
            f"{name}={obs.fields[name]}"
            for name, prov in obs.field_provenance.items()
            if prov.get("event_id") == str(event_id) and obs.fields.get(name) is not None
        ]
        if supplied:
            facts.append(f"Participant reported {obs.observation_type}: {', '.join(supplied)}.")
    return facts


def build_context_events(
    journey: Journey,
    events: Sequence[ParticipantEvent],
    observations: Sequence[Observation],
    *,
    project_types: Sequence[EventType],
    include_observations: bool,
) -> list[ContextEvent]:
    scope = ContextScope(
        tenant_id=journey.tenant_id, journey_id=journey.id, participant_id=journey.participant_id
    )
    out: list[ContextEvent] = []
    for event in events:
        kind = _EVENT_KIND.get(event.event_type)
        text = event.payload.get("text") or event.payload.get("summary")
        if kind and event.event_type in project_types and isinstance(text, str) and text:
            out.append(
                ContextEvent(
                    scope=scope,
                    source_event_id=event.id,
                    kind=kind,
                    text=text,
                    occurred_at=event.occurred_at,
                    domain_pack=journey.domain_pack,
                    source_evidence_ids=list(event.evidence_refs),
                )
            )
        if include_observations:
            facts = observation_facts(observations, event.id)
            if facts:
                out.append(
                    ContextEvent(
                        scope=scope,
                        source_event_id=event.id,
                        kind=ContextItemKind.OBSERVATION_SUMMARY,
                        text=" ".join(facts),
                        occurred_at=event.occurred_at,
                        domain_pack=journey.domain_pack,
                    )
                )
    return out


class ContextProjectionService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        packs: DomainPackRegistry,
        provider: ContextMemoryProvider,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._packs = packs
        self.provider = provider

    async def _load(
        self, repos: Repositories, tenant_id: UUID, journey_id: UUID
    ) -> tuple[Journey | None, str | None]:
        journey = await repos.journeys.get(tenant_id, journey_id)
        if journey is None:
            return None, "journey not found"
        if journey.status is JourneyStatus.PROCESSING_RESTRICTED:
            return journey, "processing restricted"
        scopes = await repos.consents.granted_scopes(tenant_id, journey.participant_id, journey_id)
        if ConsentScope.CONTEXT_PROJECTION not in scopes:
            return journey, "no context_projection consent"
        return journey, None

    async def project_events(
        self, tenant_id: UUID, journey_id: UUID, event_ids: Sequence[UUID]
    ) -> ProjectionOutcome:
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            journey, skip = await self._load(repos, tenant_id, journey_id)
            if journey is None or skip:
                log.info("context.projection.skipped", reason=skip)
                return ProjectionOutcome(retained=0, skipped_reason=skip)
            pack = self._packs.get(journey.domain_pack)
            events = await repos.events.get_many(tenant_id, journey_id, event_ids)
            observations = await repos.observations.list_for_journey(tenant_id, journey_id)
        context_events = build_context_events(
            journey,
            events,
            observations,
            project_types=pack.memory.project_event_types,
            include_observations=pack.memory.project_observation_summaries,
        )
        for ce in context_events:
            await self.provider.retain_event(ce)
        log.info(
            "context.projection.completed",
            provider=self.provider.name,
            retained=len(context_events),
        )
        return ProjectionOutcome(retained=len(context_events))

    async def rebuild_journey(self, tenant_id: UUID, journey_id: UUID) -> RebuildResult:
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            journey, skip = await self._load(repos, tenant_id, journey_id)
            if journey is None:
                raise LookupError("journey not found")
            if skip:
                removed = await self.provider.forget_journey(tenant_id, journey_id)
                log.info("context.rebuild.cleared", reason=skip, removed=removed)
                return RebuildResult(provider=self.provider.name, removed=removed, retained=0)
            pack = self._packs.get(journey.domain_pack)
            events = await repos.events.list_for_journey(tenant_id, journey_id, limit=10_000)
            observations = await repos.observations.list_for_journey(tenant_id, journey_id)
        context_events = build_context_events(
            journey,
            events,
            observations,
            project_types=pack.memory.project_event_types,
            include_observations=pack.memory.project_observation_summaries,
        )
        scope = ContextScope(
            tenant_id=tenant_id, journey_id=journey_id, participant_id=journey.participant_id
        )
        result = await self.provider.rebuild_journey(scope, context_events)
        log.info(
            "context.rebuild.completed",
            provider=result.provider,
            removed=result.removed,
            retained=result.retained,
        )
        return result

    async def forget_journey(self, tenant_id: UUID, journey_id: UUID) -> int:
        removed = await self.provider.forget_journey(tenant_id, journey_id)
        log.info("context.forget.completed", provider=self.provider.name, removed=removed)
        return removed
