"""Temporal activities.

Activities are the only place workflows touch the outside world. They take ids,
load canonical data from Postgres, call platform services, and return small
results. The same methods are invoked directly by the InlineWorkflowDispatcher, so
local/test runs exercise exactly the same code as the Temporal worker.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity

from cairn.context.projection import ContextProjectionService
from cairn.domain.enums import (
    ActorType,
    ConsentScope,
    EventType,
    JourneyStatus,
    NextActionStatus,
    NextActionType,
    RetentionClass,
)
from cairn.domain.models import NextAction, ParticipantEvent
from cairn.domain_packs.registry import DomainPackRegistry
from cairn.evidence.store import EvidenceStore
from cairn.observability.logging import get_logger
from cairn.persistence.repositories import Repositories
from cairn.reporting.service import NoReportTemplate, build_report
from cairn.workflows.types import (
    ConsentRevocationInput,
    ConsentRevocationResult,
    JourneyRef,
    ProjectionRequest,
)

log = get_logger(__name__)

_RESTRICTING = {ConsentScope.CONVERSATION}
_FORGET_CONTEXT = {ConsentScope.CONVERSATION, ConsentScope.CONTEXT_PROJECTION}
_EVIDENCE = {ConsentScope.CONVERSATION, ConsentScope.EVIDENCE}
_DELETE_ON_REVOCATION = {RetentionClass.DELETE_ON_REVOCATION, RetentionClass.STANDARD}


class CairnActivities:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        packs: DomainPackRegistry,
        projection: ContextProjectionService,
        evidence_store: EvidenceStore,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._packs = packs
        self._projection = projection
        self._evidence = evidence_store

    # ------------------------------------------------------------- context

    @activity.defn(name="cairn.project_events")
    async def project_events(self, req: ProjectionRequest) -> int:
        outcome = await self._projection.project_events(
            UUID(req.tenant_id), UUID(req.journey_id), [UUID(e) for e in req.event_ids]
        )
        return outcome.retained

    @activity.defn(name="cairn.rebuild_context")
    async def rebuild_context(self, ref: JourneyRef) -> int:
        result = await self._projection.rebuild_journey(UUID(ref.tenant_id), UUID(ref.journey_id))
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            journey = await repos.journeys.get(UUID(ref.tenant_id), UUID(ref.journey_id))
            if journey:
                await repos.events.append(
                    ParticipantEvent(
                        tenant_id=journey.tenant_id,
                        journey_id=journey.id,
                        participant_id=journey.participant_id,
                        event_type=EventType.CONTEXT_REBUILT,
                        actor_type=ActorType.SYSTEM,
                        source="workflow",
                        payload={
                            "provider": result.provider,
                            "removed": result.removed,
                            "retained": result.retained,
                        },
                    )
                )
                await session.commit()
        return result.retained

    # ------------------------------------------------------------- journey

    @activity.defn(name="cairn.issue_reminder")
    async def issue_reminder(self, ref: JourneyRef) -> str | None:
        """Record a SEND_REMINDER next action. Delivery channels are a later integration."""
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            journey = await repos.journeys.get(UUID(ref.tenant_id), UUID(ref.journey_id))
            if journey is None or journey.status is not JourneyStatus.ACTIVE:
                return None
            pack = self._packs.get(journey.domain_pack)
            event = await repos.events.append(
                ParticipantEvent(
                    tenant_id=journey.tenant_id,
                    journey_id=journey.id,
                    participant_id=journey.participant_id,
                    event_type=EventType.REMINDER_ISSUED,
                    actor_type=ActorType.SYSTEM,
                    source="workflow",
                    domain_pack=pack.id,
                    domain_pack_version=pack.version,
                    payload={"channel": "none"},
                )
            )
            action = await repos.next_actions.add(
                NextAction(
                    tenant_id=journey.tenant_id,
                    journey_id=journey.id,
                    participant_id=journey.participant_id,
                    action_type=NextActionType.SEND_REMINDER,
                    status=NextActionStatus.COMPLETED,
                    source="workflow",
                    reason=f"no participant reply within {pack.planner.follow_up_after_hours}h",
                    source_event_id=event.id,
                    domain_pack=pack.id,
                    domain_pack_version=pack.version,
                )
            )
            await session.commit()
            log.info("journey.reminder.issued", journey_id=ref.journey_id)
            return str(action.id)

    @activity.defn(name="cairn.generate_report")
    async def generate_report(self, ref: JourneyRef) -> str | None:
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            journey = await repos.journeys.get(UUID(ref.tenant_id), UUID(ref.journey_id))
            if journey is None:
                return None
            pack = self._packs.get(journey.domain_pack)
            observations = await repos.observations.list_for_journey(journey.tenant_id, journey.id)
            try:
                report = build_report(pack, journey, observations)
            except NoReportTemplate:
                return None
            await repos.events.append(
                ParticipantEvent(
                    tenant_id=journey.tenant_id,
                    journey_id=journey.id,
                    participant_id=journey.participant_id,
                    event_type=EventType.REPORT_GENERATED,
                    actor_type=ActorType.SYSTEM,
                    source="workflow",
                    domain_pack=pack.id,
                    domain_pack_version=pack.version,
                    payload={
                        "report_id": str(report.id),
                        "template_id": report.template_id,
                        "template_version": report.template_version,
                        "statements": sum(len(s.statements) for s in report.sections),
                    },
                )
            )
            await session.commit()
            return str(report.id)

    # ---------------------------------------------------- consent revocation

    @activity.defn(name="cairn.mark_consent_revoked")
    async def mark_consent_revoked(self, req: ConsentRevocationInput) -> list[str]:
        """Idempotent: the API normally revoked already; this catches anything left granted."""
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            revoked = await repos.consents.revoke(
                UUID(req.tenant_id), UUID(req.journey_id), [ConsentScope(s) for s in req.scopes]
            )
            await session.commit()
            return sorted({*req.consent_ids, *(str(c.id) for c in revoked)})

    @activity.defn(name="cairn.restrict_processing")
    async def restrict_processing(self, req: ConsentRevocationInput) -> bool:
        if not _RESTRICTING & {ConsentScope(s) for s in req.scopes}:
            return False
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            await repos.journeys.set_status(
                UUID(req.tenant_id), UUID(req.journey_id), JourneyStatus.PROCESSING_RESTRICTED
            )
            await repos.next_actions.resolve_awaiting(
                UUID(req.tenant_id), UUID(req.journey_id), NextActionStatus.BLOCKED
            )
            await session.commit()
        return True

    @activity.defn(name="cairn.forget_context")
    async def forget_context(self, req: ConsentRevocationInput) -> int:
        if not _FORGET_CONTEXT & {ConsentScope(s) for s in req.scopes}:
            return 0
        return await self._projection.forget_journey(UUID(req.tenant_id), UUID(req.journey_id))

    @activity.defn(name="cairn.apply_evidence_retention")
    async def apply_evidence_retention(self, req: ConsentRevocationInput) -> list[int]:
        """Returns [deleted, retained]."""
        if not _EVIDENCE & {ConsentScope(s) for s in req.scopes}:
            return [0, 0]
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            items = await repos.evidence.list_for_journey(UUID(req.tenant_id), UUID(req.journey_id))
            to_delete = [e for e in items if e.retention_class in _DELETE_ON_REVOCATION]
            for item in to_delete:
                await self._evidence.delete(item.object_key)
            await repos.evidence.mark_deleted(UUID(req.tenant_id), [e.id for e in to_delete])
            await session.commit()
        return [len(to_delete), len(items) - len(to_delete)]

    @activity.defn(name="cairn.record_revocation_audit")
    async def record_revocation_audit(
        self, req: ConsentRevocationInput, result: ConsentRevocationResult
    ) -> bool:
        async with self._sessionmaker() as session:
            repos = Repositories(session)
            await repos.audit.record(
                tenant_id=UUID(req.tenant_id),
                actor_id=req.requested_by,
                action="consent:revoke",
                resource_type="journey",
                resource_id=req.journey_id,
                outcome="completed",
                request_id=req.request_id,
                details={
                    "scopes": req.scopes,
                    "revoked_consent_ids": result.revoked_consent_ids,
                    "processing_restricted": result.processing_restricted,
                    "context_items_removed": result.context_items_removed,
                    "evidence_deleted": result.evidence_deleted,
                    "evidence_retained": result.evidence_retained,
                },
            )
            await session.commit()
        return True
