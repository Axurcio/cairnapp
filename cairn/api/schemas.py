"""API models. Separate from domain and persistence models by design.

Decision artefacts (PolicyDecision, PlannerDecision, ResponseIntent...) are
exposed as-is under ``explanation`` because they exist to be inspected.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cairn.ai.rendering import RenderedResponse
from cairn.domain.enums import ConsentScope, JourneyStatus, NextActionStatus, NextActionType
from cairn.guardrails.provider import GuardrailCheck
from cairn.journeys.message_service import ContextSummary, ExtractionSummary, SafetySummary
from cairn.planner.intents import ResponseIntent
from cairn.planner.planner import PlannerDecision
from cairn.policies.response_policy import PolicyDecision


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # Upper bound keeps a single request from tying up the password hasher.
    password: str = Field(min_length=1, max_length=1024)


class AccountOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    actor_id: str
    roles: list[str]
    tenant_id: UUID | None
    tenant_name: str | None
    participant_id: UUID | None


class SessionOut(BaseModel):
    account: AccountOut
    # Echo this in the X-CSRF-Token header on every POST/PUT/PATCH/DELETE.
    csrf_token: str
    expires_at: datetime


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantOut(APIModel):
    id: UUID
    name: str
    created_at: datetime


class ParticipantCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    external_ref: str | None = Field(default=None, max_length=200)
    is_synthetic: bool = False


class ParticipantOut(APIModel):
    id: UUID
    display_name: str
    external_ref: str | None
    is_synthetic: bool
    created_at: datetime


class JourneyCreate(BaseModel):
    participant_id: UUID
    domain_pack: str
    title: str = Field(min_length=1, max_length=200)
    consents: list[ConsentScope] = Field(default_factory=lambda: list(ConsentScope))
    is_synthetic: bool = False


class JourneyOut(APIModel):
    id: UUID
    participant_id: UUID
    title: str
    domain_pack: str
    domain_pack_version: str
    status: JourneyStatus
    is_synthetic: bool
    started_at: datetime


class JourneySummaryOut(JourneyOut):
    participant_display_name: str | None
    domain_pack_name: str | None


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    occurred_at: datetime | None = None


class NextActionOut(APIModel):
    id: UUID
    action_type: NextActionType
    status: NextActionStatus
    reason: str
    question_id: str | None
    field: str | None
    activity_id: str | None
    observation_id: UUID | None
    policy_id: str | None
    policy_version: str | None
    domain_pack: str | None
    domain_pack_version: str | None
    occurred_at: datetime
    explanation: dict[str, Any] = Field(default_factory=dict)


class ObservationOut(APIModel):
    id: UUID
    observation_type: str
    observation_schema_version: str
    fields: dict[str, Any]
    status: str
    confirmed: bool
    confidence: float | None
    source_event_ids: list[UUID]
    source_evidence_ids: list[UUID]
    field_provenance: dict[str, dict[str, Any]]
    extraction_version: str
    domain_pack: str | None
    domain_pack_version: str | None
    occurred_at: datetime
    updated_at: datetime


class PatternEvaluationOut(APIModel):
    rule_id: str
    rule_version: str
    algorithm: str
    algorithm_version: str
    matched: bool
    result: dict[str, Any]
    suggested_action: str | None
    evidence_refs: list[UUID]
    evaluated_at: datetime


class MessageExplanation(BaseModel):
    policy_decision: PolicyDecision | None
    planner_decision: PlannerDecision
    intent: ResponseIntent
    extraction: ExtractionSummary | None
    safety: SafetySummary
    guardrails: list[GuardrailCheck]
    context: ContextSummary
    trace: list[str]


class MessageResponse(BaseModel):
    journey_id: UUID
    participant_event_id: UUID
    assistant_event_id: UUID
    response: RenderedResponse
    next_action: NextActionOut
    observation: ObservationOut | None
    pattern_evaluations: list[PatternEvaluationOut]
    explanation: MessageExplanation


class TimelineEntry(BaseModel):
    event_id: UUID
    event_type: str
    actor_type: str
    occurred_at: datetime
    source: str
    text: str | None = None
    evidence_refs: list[UUID] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceOut(APIModel):
    id: UUID
    content_type: str
    capture_type: str
    size_bytes: int
    checksum_sha256: str
    retention_class: str
    consent_scope: str
    created_at: datetime
    event_id: UUID | None = None


class StatusOut(BaseModel):
    status: str


class ConsentsOut(BaseModel):
    granted: list[ConsentScope]


class ConsentRevokeRequest(BaseModel):
    scopes: list[ConsentScope] = Field(min_length=1)


class DomainPackSummary(BaseModel):
    id: str
    name: str
    version: str
    classification: str
    regulatory_profile: str
    synthetic_sample: bool
    description: str


class DomainPackDetail(DomainPackSummary):
    checksum: str
    terminology: dict[str, str]
    observation_types: dict[str, dict[str, Any]]
    response_policies: list[dict[str, Any]]
    question_protocols: list[dict[str, Any]]
    patterns: list[dict[str, Any]]
    activities: list[str]
    safety_policy: dict[str, str]
    planner_version: str
    report_templates: list[str]
