"""Canonical, domain-neutral Cairn domain model.

These Pydantic objects are the platform's language. They are deliberately
generic: nothing here knows about tremors or mentoring. Domain-specific meaning
arrives through Domain Packs (observation schemas, policies, terminology) and is
carried in typed-but-open fields such as :attr:`Observation.fields`.

Three representations are kept separate:

* domain model (this module) - what the business logic reasons about
* persistence model (:mod:`cairn.persistence.models`) - how it is stored
* API model (:mod:`cairn.api.schemas`) - what clients see

Objects marked "domain type only" are defined so the vocabulary is complete,
but are not yet persisted by the scaffold.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from cairn.domain.enums import (
    ActorType,
    ConsentScope,
    ConsentStatus,
    EventType,
    JourneyStatus,
    NextActionStatus,
    NextActionType,
    ObservationStatus,
    RelationshipType,
    RetentionClass,
)

SCHEMA_VERSION = "1"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Provenance(BaseModel):
    """Where a fact came from. Every derived object must be traceable to sources."""

    model_config = ConfigDict(frozen=True)

    source_event_ids: tuple[UUID, ...] = ()
    source_evidence_ids: tuple[UUID, ...] = ()
    produced_by: str = Field(description="component that produced it, e.g. 'mock-ai:extract'")
    produced_by_version: str = "0"
    domain_pack: str | None = None
    domain_pack_version: str | None = None
    rule_id: str | None = None
    rule_version: str | None = None
    notes: str | None = None


class DomainObject(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    created_at: datetime = Field(default_factory=utcnow)
    schema_version: str = SCHEMA_VERSION


class JourneyScoped(DomainObject):
    journey_id: UUID
    participant_id: UUID
    occurred_at: datetime = Field(default_factory=utcnow)
    source: str = "api"
    domain_pack: str | None = None
    domain_pack_version: str | None = None


# --------------------------------------------------------------------- tenancy


class Tenant(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    name: str
    created_at: datetime = Field(default_factory=utcnow)
    schema_version: str = SCHEMA_VERSION


class Participant(DomainObject):
    display_name: str
    external_ref: str | None = None
    # Synthetic data must be labelled so it can never be confused with real records.
    is_synthetic: bool = False


class Journey(DomainObject):
    participant_id: UUID
    title: str
    domain_pack: str
    domain_pack_version: str
    status: JourneyStatus = JourneyStatus.ACTIVE
    started_at: datetime = Field(default_factory=utcnow)
    is_synthetic: bool = False


class Relationship(DomainObject):
    """A facilitator (mentor, clinician, caregiver...) linked to a participant."""

    participant_id: UUID
    actor_id: str
    relationship_type: RelationshipType
    journey_id: UUID | None = None
    active: bool = True


class UserAccount(BaseModel):
    """A person who signs in to the website. Resolves to an ``ActorContext`` per request.

    ``actor_id`` is the identity used for audit and relationships, so a facilitator's
    account must carry the same actor id as their :class:`Relationship` rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    # None only for platform administrators, who act above any tenant.
    tenant_id: UUID | None
    email: str
    display_name: str
    password_hash: str
    actor_id: str
    roles: list[str]
    participant_id: UUID | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None
    schema_version: str = SCHEMA_VERSION


class LoginSession(BaseModel):
    """A signed-in browser session. Only a hash of the bearer token is stored."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    token_hash: str
    csrf_token: str
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    revoked_at: datetime | None = None


class Permission(BaseModel):
    """Domain type only: a scope granted to an actor over a resource."""

    actor_id: str
    scope: str
    resource_type: str
    resource_id: UUID | None = None


class Consent(DomainObject):
    participant_id: UUID
    journey_id: UUID | None = None
    scope: ConsentScope
    status: ConsentStatus = ConsentStatus.GRANTED
    granted_at: datetime = Field(default_factory=utcnow)
    revoked_at: datetime | None = None
    policy_version: str = "1"
    source: str = "api"


# ------------------------------------------------------------------ journey data


class Goal(JourneyScoped):
    """Domain type only."""

    description: str
    status: str = "open"


class ParticipantEvent(JourneyScoped):
    """Append-only record of something that happened in a journey.

    The canonical log. Observations, decisions and context projections are all
    derived from these events and keep references back to them.
    """

    event_type: EventType
    actor_type: ActorType
    payload: dict[str, Any] = Field(default_factory=dict)
    consent_scope: ConsentScope | None = None
    evidence_refs: list[UUID] = Field(default_factory=list)


class Observation(JourneyScoped):
    """A structured, Domain-Pack-typed fact Cairn has accepted from the participant."""

    observation_type: str
    observation_schema_version: str
    fields: dict[str, Any] = Field(default_factory=dict)
    status: ObservationStatus = ObservationStatus.COLLECTING
    confirmed: bool = False
    confidence: float | None = None
    source_event_ids: list[UUID] = Field(default_factory=list)
    source_evidence_ids: list[UUID] = Field(default_factory=list)
    extraction_version: str
    # Per-field provenance: which event supplied which value.
    field_provenance: dict[str, dict[str, Any]] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)


class Evidence(JourneyScoped):
    content_type: str
    capture_type: str
    size_bytes: int
    checksum_sha256: str
    object_key: str
    consent_scope: ConsentScope = ConsentScope.EVIDENCE
    retention_class: RetentionClass = RetentionClass.STANDARD
    provenance: Provenance
    deleted_at: datetime | None = None


class Activity(BaseModel):
    """Domain type only: an activity instance requested of a participant."""

    activity_id: str
    journey_id: UUID
    requested_at: datetime = Field(default_factory=utcnow)


class Assessment(JourneyScoped):
    """Domain type only: a structured instrument result."""

    instrument_id: str
    scores: dict[str, float] = Field(default_factory=dict)


class Baseline(JourneyScoped):
    """Domain type only: a reference value for a derived feature."""

    feature_id: str
    value: float
    window_days: int


class DerivedFeature(JourneyScoped):
    """Domain type only: a computed value with provenance."""

    feature_id: str
    value: float
    provenance: Provenance


class PatternEvaluation(JourneyScoped):
    rule_id: str
    rule_version: str
    algorithm: str
    algorithm_version: str
    matched: bool
    result: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str | None = None
    evidence_refs: list[UUID] = Field(default_factory=list)
    source_event_ids: list[UUID] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=utcnow)


class NextAction(JourneyScoped):
    action_type: NextActionType
    status: NextActionStatus
    reason: str
    question_id: str | None = None
    field: str | None = None
    activity_id: str | None = None
    observation_id: UUID | None = None
    policy_id: str | None = None
    policy_version: str | None = None
    source_event_id: UUID | None = None
    explanation: dict[str, Any] = Field(default_factory=dict)
    resolved_at: datetime | None = None


class ConversationTurn(BaseModel):
    """Domain type only: a participant message paired with Cairn's reply."""

    participant_event_id: UUID
    assistant_event_id: UUID | None


class Reflection(JourneyScoped):
    """Domain type only: a participant's own reflection on their journey."""

    text_event_id: UUID


class ReportStatement(BaseModel):
    """A descriptive statement in a report, always traceable to its sources."""

    text: str
    observation_id: UUID | None = None
    source_event_ids: list[UUID] = Field(default_factory=list)
    source_evidence_ids: list[UUID] = Field(default_factory=list)


class ReportSection(BaseModel):
    title: str
    statements: list[ReportStatement] = Field(default_factory=list)


class Report(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    journey_id: UUID
    template_id: str
    template_version: str
    domain_pack: str
    domain_pack_version: str
    generated_at: datetime = Field(default_factory=utcnow)
    disclaimer: str
    sections: list[ReportSection] = Field(default_factory=list)
