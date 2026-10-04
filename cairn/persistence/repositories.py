"""Tenant-scoped repositories.

Every read and write takes an explicit ``tenant_id`` and every query filters on
it. There is deliberately no "get by id" without a tenant: cross-tenant access is
impossible to express through this API. Rows are mapped to domain objects on the
way out, so ORM models never leak into business logic or the API.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import JSON, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.domain.enums import (
    ConsentScope,
    ConsentStatus,
    JourneyStatus,
    NextActionStatus,
    NextActionType,
    ObservationStatus,
)
from cairn.domain.models import (
    Consent,
    Evidence,
    Journey,
    LoginSession,
    NextAction,
    Observation,
    Participant,
    ParticipantEvent,
    PatternEvaluation,
    Relationship,
    Tenant,
    UserAccount,
    utcnow,
)
from cairn.persistence.base import Base
from cairn.persistence.models import (
    AuditEventRow,
    ConsentRow,
    EvidenceRow,
    JourneyEventRow,
    JourneyRow,
    LoginSessionRow,
    NextActionRow,
    ObservationRow,
    ParticipantRow,
    PatternEvaluationRow,
    RelationshipRow,
    TenantRow,
    UserRow,
)


def to_row_values(model: BaseModel, row_cls: type[Base]) -> dict[str, Any]:
    """Map a domain object onto ORM column values (JSON columns get JSON-mode values)."""
    py = model.model_dump()
    js = model.model_dump(mode="json")
    values: dict[str, Any] = {}
    for column in row_cls.__table__.columns:
        if column.key in py:
            values[column.key] = js[column.key] if isinstance(column.type, JSON) else py[column.key]
    return values


class _Repo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class TenantRepository(_Repo):
    async def add(self, tenant: Tenant) -> Tenant:
        self.session.add(TenantRow(**to_row_values(tenant, TenantRow)))
        await self.session.flush()
        return tenant

    async def get(self, tenant_id: UUID) -> Tenant | None:
        row = await self.session.get(TenantRow, tenant_id)
        return Tenant.model_validate(row) if row else None

    async def find_by_name(self, name: str) -> Tenant | None:
        row = await self.session.scalar(select(TenantRow).where(TenantRow.name == name))
        return Tenant.model_validate(row) if row else None


class ParticipantRepository(_Repo):
    async def add(self, participant: Participant) -> Participant:
        self.session.add(ParticipantRow(**to_row_values(participant, ParticipantRow)))
        await self.session.flush()
        return participant

    async def get(self, tenant_id: UUID, participant_id: UUID) -> Participant | None:
        row = await self.session.scalar(
            select(ParticipantRow).where(
                ParticipantRow.tenant_id == tenant_id, ParticipantRow.id == participant_id
            )
        )
        return Participant.model_validate(row) if row else None

    async def get_many(self, tenant_id: UUID, participant_ids: Sequence[UUID]) -> list[Participant]:
        if not participant_ids:
            return []
        rows = await self.session.scalars(
            select(ParticipantRow).where(
                ParticipantRow.tenant_id == tenant_id,
                ParticipantRow.id.in_(list(participant_ids)),
            )
        )
        return [Participant.model_validate(r) for r in rows]


class JourneyRepository(_Repo):
    async def add(self, journey: Journey) -> Journey:
        self.session.add(JourneyRow(**to_row_values(journey, JourneyRow)))
        await self.session.flush()
        return journey

    async def get(self, tenant_id: UUID, journey_id: UUID) -> Journey | None:
        row = await self.session.scalar(
            select(JourneyRow).where(JourneyRow.tenant_id == tenant_id, JourneyRow.id == journey_id)
        )
        return Journey.model_validate(row) if row else None

    async def list_for_participant(self, tenant_id: UUID, participant_id: UUID) -> list[Journey]:
        rows = await self.session.scalars(
            select(JourneyRow).where(
                JourneyRow.tenant_id == tenant_id, JourneyRow.participant_id == participant_id
            )
        )
        return [Journey.model_validate(r) for r in rows]

    async def list_for_tenant(self, tenant_id: UUID) -> list[Journey]:
        rows = await self.session.scalars(
            select(JourneyRow)
            .where(JourneyRow.tenant_id == tenant_id)
            .order_by(JourneyRow.started_at.desc())
        )
        return [Journey.model_validate(r) for r in rows]

    async def set_status(self, tenant_id: UUID, journey_id: UUID, status: JourneyStatus) -> None:
        await self.session.execute(
            update(JourneyRow)
            .where(JourneyRow.tenant_id == tenant_id, JourneyRow.id == journey_id)
            .values(status=status)
        )


class EventRepository(_Repo):
    """Append-only: there is no update or delete method by design."""

    async def append(self, event: ParticipantEvent) -> ParticipantEvent:
        self.session.add(JourneyEventRow(**to_row_values(event, JourneyEventRow)))
        await self.session.flush()
        return event

    async def list_for_journey(
        self,
        tenant_id: UUID,
        journey_id: UUID,
        *,
        limit: int = 200,
        event_types: Sequence[str] | None = None,
    ) -> list[ParticipantEvent]:
        stmt = select(JourneyEventRow).where(
            JourneyEventRow.tenant_id == tenant_id, JourneyEventRow.journey_id == journey_id
        )
        if event_types:
            stmt = stmt.where(JourneyEventRow.event_type.in_(list(event_types)))
        stmt = stmt.order_by(JourneyEventRow.occurred_at, JourneyEventRow.created_at).limit(limit)
        return [ParticipantEvent.model_validate(r) for r in await self.session.scalars(stmt)]

    async def get_many(
        self, tenant_id: UUID, journey_id: UUID, event_ids: Sequence[UUID]
    ) -> list[ParticipantEvent]:
        rows = await self.session.scalars(
            select(JourneyEventRow)
            .where(
                JourneyEventRow.tenant_id == tenant_id,
                JourneyEventRow.journey_id == journey_id,
                JourneyEventRow.id.in_(list(event_ids)),
            )
            .order_by(JourneyEventRow.occurred_at)
        )
        return [ParticipantEvent.model_validate(r) for r in rows]


class ObservationRepository(_Repo):
    async def add(self, observation: Observation) -> Observation:
        self.session.add(ObservationRow(**to_row_values(observation, ObservationRow)))
        await self.session.flush()
        return observation

    async def save(self, observation: Observation) -> Observation:
        values = to_row_values(observation, ObservationRow)
        await self.session.execute(
            update(ObservationRow)
            .where(
                ObservationRow.tenant_id == observation.tenant_id,
                ObservationRow.id == observation.id,
            )
            .values(**{k: v for k, v in values.items() if k not in ("id", "tenant_id")})
        )
        return observation

    async def get(self, tenant_id: UUID, observation_id: UUID) -> Observation | None:
        row = await self.session.scalar(
            select(ObservationRow).where(
                ObservationRow.tenant_id == tenant_id, ObservationRow.id == observation_id
            )
        )
        return Observation.model_validate(row) if row else None

    async def list_for_journey(
        self,
        tenant_id: UUID,
        journey_id: UUID,
        *,
        observation_type: str | None = None,
        since: datetime | None = None,
    ) -> list[Observation]:
        stmt = select(ObservationRow).where(
            ObservationRow.tenant_id == tenant_id, ObservationRow.journey_id == journey_id
        )
        if observation_type:
            stmt = stmt.where(ObservationRow.observation_type == observation_type)
        if since:
            stmt = stmt.where(ObservationRow.occurred_at >= since)
        stmt = stmt.order_by(ObservationRow.occurred_at)
        return [Observation.model_validate(r) for r in await self.session.scalars(stmt)]

    async def mark_incomplete(
        self, tenant_id: UUID, journey_id: UUID, observation_type: str
    ) -> None:
        await self.session.execute(
            update(ObservationRow)
            .where(
                ObservationRow.tenant_id == tenant_id,
                ObservationRow.journey_id == journey_id,
                ObservationRow.observation_type == observation_type,
                ObservationRow.status == ObservationStatus.COLLECTING,
            )
            .values(status=ObservationStatus.INCOMPLETE, updated_at=utcnow())
        )


class NextActionRepository(_Repo):
    async def add(self, action: NextAction) -> NextAction:
        self.session.add(NextActionRow(**to_row_values(action, NextActionRow)))
        await self.session.flush()
        return action

    async def list_for_journey(
        self,
        tenant_id: UUID,
        journey_id: UUID,
        *,
        status: NextActionStatus | None = None,
        limit: int = 100,
    ) -> list[NextAction]:
        stmt = select(NextActionRow).where(
            NextActionRow.tenant_id == tenant_id, NextActionRow.journey_id == journey_id
        )
        if status:
            stmt = stmt.where(NextActionRow.status == status)
        stmt = stmt.order_by(NextActionRow.created_at.desc()).limit(limit)
        return [NextAction.model_validate(r) for r in await self.session.scalars(stmt)]

    async def pending_question(self, tenant_id: UUID, journey_id: UUID) -> NextAction | None:
        row = await self.session.scalar(
            select(NextActionRow)
            .where(
                NextActionRow.tenant_id == tenant_id,
                NextActionRow.journey_id == journey_id,
                NextActionRow.action_type == NextActionType.ASK_QUESTION,
                NextActionRow.status == NextActionStatus.AWAITING_REPLY,
            )
            .order_by(NextActionRow.created_at.desc())
            .limit(1)
        )
        return NextAction.model_validate(row) if row else None

    async def resolve_awaiting(
        self, tenant_id: UUID, journey_id: UUID, status: NextActionStatus
    ) -> None:
        await self.session.execute(
            update(NextActionRow)
            .where(
                NextActionRow.tenant_id == tenant_id,
                NextActionRow.journey_id == journey_id,
                NextActionRow.status == NextActionStatus.AWAITING_REPLY,
            )
            .values(status=status, resolved_at=utcnow())
        )

    async def history(
        self,
        tenant_id: UUID,
        journey_id: UUID,
        *,
        since: datetime,
        action_types: Sequence[NextActionType],
    ) -> list[NextAction]:
        rows = await self.session.scalars(
            select(NextActionRow)
            .where(
                NextActionRow.tenant_id == tenant_id,
                NextActionRow.journey_id == journey_id,
                NextActionRow.action_type.in_(list(action_types)),
                NextActionRow.created_at >= since,
            )
            .order_by(NextActionRow.created_at)
        )
        return [NextAction.model_validate(r) for r in rows]


class PatternEvaluationRepository(_Repo):
    async def add_many(self, evaluations: Sequence[PatternEvaluation]) -> None:
        for e in evaluations:
            self.session.add(PatternEvaluationRow(**to_row_values(e, PatternEvaluationRow)))
        await self.session.flush()


class ConsentRepository(_Repo):
    async def add(self, consent: Consent) -> Consent:
        self.session.add(ConsentRow(**to_row_values(consent, ConsentRow)))
        await self.session.flush()
        return consent

    async def granted_scopes(
        self, tenant_id: UUID, participant_id: UUID, journey_id: UUID
    ) -> set[ConsentScope]:
        rows = await self.session.scalars(
            select(ConsentRow).where(
                ConsentRow.tenant_id == tenant_id,
                ConsentRow.participant_id == participant_id,
                (ConsentRow.journey_id == journey_id) | (ConsentRow.journey_id.is_(None)),
                ConsentRow.status == ConsentStatus.GRANTED,
            )
        )
        return {ConsentScope(r.scope) for r in rows}

    async def revoke(
        self, tenant_id: UUID, journey_id: UUID, scopes: Sequence[ConsentScope]
    ) -> list[Consent]:
        rows = list(
            await self.session.scalars(
                select(ConsentRow).where(
                    ConsentRow.tenant_id == tenant_id,
                    ConsentRow.journey_id == journey_id,
                    ConsentRow.scope.in_([s.value for s in scopes]),
                    ConsentRow.status == ConsentStatus.GRANTED,
                )
            )
        )
        now = utcnow()
        for row in rows:
            row.status = ConsentStatus.REVOKED
            row.revoked_at = now
        await self.session.flush()
        return [Consent.model_validate(r) for r in rows]


class RelationshipRepository(_Repo):
    async def add(self, relationship: Relationship) -> Relationship:
        self.session.add(RelationshipRow(**to_row_values(relationship, RelationshipRow)))
        await self.session.flush()
        return relationship

    async def has_active(
        self, tenant_id: UUID, actor_id: str, participant_id: UUID, journey_id: UUID | None
    ) -> bool:
        stmt = select(RelationshipRow.id).where(
            RelationshipRow.tenant_id == tenant_id,
            RelationshipRow.actor_id == actor_id,
            RelationshipRow.participant_id == participant_id,
            RelationshipRow.active.is_(True),
        )
        if journey_id is not None:
            stmt = stmt.where(
                (RelationshipRow.journey_id == journey_id) | (RelationshipRow.journey_id.is_(None))
            )
        return (await self.session.scalar(stmt.limit(1))) is not None

    async def list_active_for_actor(self, tenant_id: UUID, actor_id: str) -> list[Relationship]:
        rows = await self.session.scalars(
            select(RelationshipRow).where(
                RelationshipRow.tenant_id == tenant_id,
                RelationshipRow.actor_id == actor_id,
                RelationshipRow.active.is_(True),
            )
        )
        return [Relationship.model_validate(r) for r in rows]


class EvidenceRepository(_Repo):
    async def add(self, evidence: Evidence) -> Evidence:
        self.session.add(EvidenceRow(**to_row_values(evidence, EvidenceRow)))
        await self.session.flush()
        return evidence

    async def list_for_journey(
        self, tenant_id: UUID, journey_id: UUID, *, include_deleted: bool = False
    ) -> list[Evidence]:
        stmt = select(EvidenceRow).where(
            EvidenceRow.tenant_id == tenant_id, EvidenceRow.journey_id == journey_id
        )
        if not include_deleted:
            stmt = stmt.where(EvidenceRow.deleted_at.is_(None))
        return [Evidence.model_validate(r) for r in await self.session.scalars(stmt)]

    async def mark_deleted(self, tenant_id: UUID, evidence_ids: Sequence[UUID]) -> None:
        if not evidence_ids:
            return
        await self.session.execute(
            update(EvidenceRow)
            .where(EvidenceRow.tenant_id == tenant_id, EvidenceRow.id.in_(list(evidence_ids)))
            .values(deleted_at=utcnow())
        )


class AuditRepository(_Repo):
    async def record(
        self,
        *,
        tenant_id: UUID | None,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: UUID | str | None,
        outcome: str,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        self.session.add(
            AuditEventRow(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else None,
                outcome=outcome,
                details=details or {},
                request_id=request_id,
                occurred_at=utcnow(),
            )
        )
        await self.session.flush()


class UserRepository(_Repo):
    """Sign-in accounts.

    Unlike every other repository this one is not tenant-scoped: sign-in looks a user up
    by email before any tenant is known. Callers must derive the tenant from the user row.
    """

    async def add(self, user: UserAccount) -> UserAccount:
        self.session.add(UserRow(**to_row_values(user, UserRow)))
        await self.session.flush()
        return user

    async def get(self, user_id: UUID) -> UserAccount | None:
        row = await self.session.get(UserRow, user_id)
        return UserAccount.model_validate(row) if row else None

    async def find_by_email(self, email: str) -> UserAccount | None:
        row = await self.session.scalar(select(UserRow).where(UserRow.email == email.lower()))
        return UserAccount.model_validate(row) if row else None

    async def record_login(self, user_id: UUID, at: datetime) -> None:
        await self.session.execute(
            update(UserRow).where(UserRow.id == user_id).values(last_login_at=at)
        )


class LoginSessionRepository(_Repo):
    async def add(self, login: LoginSession) -> LoginSession:
        self.session.add(LoginSessionRow(**to_row_values(login, LoginSessionRow)))
        await self.session.flush()
        return login

    async def find_by_token_hash(self, token_hash: str) -> LoginSession | None:
        row = await self.session.scalar(
            select(LoginSessionRow).where(LoginSessionRow.token_hash == token_hash)
        )
        return LoginSession.model_validate(row) if row else None

    async def revoke(self, session_id: UUID, at: datetime) -> None:
        await self.session.execute(
            update(LoginSessionRow)
            .where(LoginSessionRow.id == session_id, LoginSessionRow.revoked_at.is_(None))
            .values(revoked_at=at)
        )


class Repositories:
    """Per-session facade over all repositories."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.participants = ParticipantRepository(session)
        self.journeys = JourneyRepository(session)
        self.events = EventRepository(session)
        self.observations = ObservationRepository(session)
        self.next_actions = NextActionRepository(session)
        self.patterns = PatternEvaluationRepository(session)
        self.consents = ConsentRepository(session)
        self.relationships = RelationshipRepository(session)
        self.evidence = EvidenceRepository(session)
        self.audit = AuditRepository(session)
        self.users = UserRepository(session)
        self.login_sessions = LoginSessionRepository(session)
