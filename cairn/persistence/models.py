"""Persistence (ORM) models for canonical Cairn data.

These rows are the source of truth. They are mapped to/from domain objects in
:mod:`cairn.persistence.repositories` and are never returned from the API directly.
JSONB is used selectively for Domain-Pack-specific payloads (observation fields,
event payloads, explanations); identity, tenancy, typing and timing are columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from cairn.domain.models import utcnow
from cairn.persistence.base import Base, JSONType, UTCDateTime


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _created() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, nullable=False, default=utcnow)


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created()
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class ParticipantRow(Base):
    __tablename__ = "participants"

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(200))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class JourneyRow(Base):
    __tablename__ = "journeys"

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    participant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("participants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    domain_pack: Mapped[str] = mapped_column(String(100), nullable=False)
    domain_pack_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    created_at: Mapped[datetime] = _created()
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class JourneyEventRow(Base):
    """Append-only canonical event log. Rows are never updated."""

    __tablename__ = "journey_events"
    __table_args__ = (
        Index(
            "ix_journey_events_tenant_journey_occurred", "tenant_id", "journey_id", "occurred_at"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    journey_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = _created()
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    consent_scope: Mapped[str | None] = mapped_column(String(64))
    evidence_refs: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    domain_pack: Mapped[str | None] = mapped_column(String(100))
    domain_pack_version: Mapped[str | None] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class ObservationRow(Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index(
            "ix_observations_tenant_journey_type_occurred",
            "tenant_id",
            "journey_id",
            "observation_type",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    journey_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    observation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    observation_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_event_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    field_provenance: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    extraction_version: Mapped[str] = mapped_column(String(32), nullable=False)
    domain_pack: Mapped[str | None] = mapped_column(String(100))
    domain_pack_version: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class EvidenceRow(Base):
    """Evidence metadata. Binary content lives in object storage at ``object_key``."""

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    journey_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    capture_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    consent_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    domain_pack: Mapped[str | None] = mapped_column(String(100))
    domain_pack_version: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class RelationshipRow(Base):
    __tablename__ = "relationships"

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    participant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("participants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    journey_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journeys.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class UserRow(Base):
    """Website sign-in accounts. Each one maps onto an ActorContext."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _id()
    # Nullable: platform administrators are not tied to a tenant.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    # Stored lower-cased; unique across tenants because sign-in happens before a tenant is known.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    roles: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    participant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class LoginSessionRow(Base):
    """Server-side browser sessions. The cookie holds a random token; only its hash is kept."""

    __tablename__ = "login_sessions"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ConsentRow(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    participant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("participants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    journey_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journeys.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class PatternEvaluationRow(Base):
    __tablename__ = "pattern_evaluations"

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    journey_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    suggested_action: Mapped[str | None] = mapped_column(String(100))
    evidence_refs: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    source_event_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    domain_pack: Mapped[str | None] = mapped_column(String(100))
    domain_pack_version: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime] = _created()
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class NextActionRow(Base):
    __tablename__ = "next_actions"
    __table_args__ = (
        Index("ix_next_actions_tenant_journey_status", "tenant_id", "journey_id", "status"),
    )

    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    journey_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    question_id: Mapped[str | None] = mapped_column(String(200))
    field: Mapped[str | None] = mapped_column(String(100))
    activity_id: Mapped[str | None] = mapped_column(String(100))
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("observations.id", ondelete="SET NULL")
    )
    policy_id: Mapped[str | None] = mapped_column(String(100))
    policy_version: Mapped[str | None] = mapped_column(String(32))
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    domain_pack: Mapped[str | None] = mapped_column(String(100))
    domain_pack_version: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")


class AuditEventRow(Base):
    """Audit trail for access-sensitive operations (reads of journeys, revocations...)."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _id()
    # Nullable: platform-level operations (e.g. tenant creation) have no tenant yet.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, index=True
    )
