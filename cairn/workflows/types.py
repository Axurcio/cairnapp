"""Workflow inputs/outputs.

Workflow state holds identifiers and small bounded values only - never domain
records, message text or evidence. Activities load what they need from Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JourneyRef:
    tenant_id: str
    journey_id: str


@dataclass(frozen=True)
class ProjectionRequest:
    tenant_id: str
    journey_id: str
    event_ids: list[str]


@dataclass(frozen=True)
class JourneyWorkflowInput:
    tenant_id: str
    journey_id: str
    follow_up_hours: float
    max_reminders: int = 3


@dataclass
class JourneyWorkflowStatus:
    replies: int = 0
    reminders_issued: int = 0
    last_event_id: str | None = None
    closed: bool = False


@dataclass(frozen=True)
class ConsentRevocationInput:
    tenant_id: str
    journey_id: str
    scopes: list[str]
    requested_by: str
    # Consents already revoked synchronously by the API (so revocation is immediate).
    consent_ids: list[str] = field(default_factory=list)
    request_id: str | None = None


@dataclass
class ConsentRevocationResult:
    revoked_consent_ids: list[str] = field(default_factory=list)
    processing_restricted: bool = False
    context_items_removed: int = 0
    evidence_deleted: int = 0
    evidence_retained: int = 0
    audit_recorded: bool = False
