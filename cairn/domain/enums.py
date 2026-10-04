"""Generic, domain-neutral enumerations shared across the platform core."""

from __future__ import annotations

from enum import StrEnum


class JourneyStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    # Consent revoked: no further participant-data processing is permitted.
    PROCESSING_RESTRICTED = "processing_restricted"
    CLOSED = "closed"


class ActorType(StrEnum):
    PARTICIPANT = "participant"
    ASSISTANT = "assistant"
    FACILITATOR = "facilitator"
    SYSTEM = "system"


class EventType(StrEnum):
    PARTICIPANT_MESSAGE = "participant.message"
    ASSISTANT_MESSAGE = "assistant.message"
    EVIDENCE_ADDED = "evidence.added"
    REMINDER_ISSUED = "reminder.issued"
    REPORT_GENERATED = "report.generated"
    CONSENT_REVOKED = "consent.revoked"
    CONTEXT_REBUILT = "context.rebuilt"


class ObservationStatus(StrEnum):
    COLLECTING = "collecting"
    COMPLETE = "complete"
    # A newer report of the same type arrived before this one was completed.
    INCOMPLETE = "incomplete"


class NextActionType(StrEnum):
    ASK_QUESTION = "ASK_QUESTION"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    REQUEST_ACTIVITY = "REQUEST_ACTIVITY"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    GENERATE_REPORT = "GENERATE_REPORT"
    WAIT = "WAIT"
    SEND_REMINDER = "SEND_REMINDER"
    ESCALATE = "ESCALATE"
    END_SESSION = "END_SESSION"


class NextActionStatus(StrEnum):
    PROPOSED = "proposed"
    # Delivered to the participant and awaiting a reply (e.g. a pending question).
    AWAITING_REPLY = "awaiting_reply"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"


class ConsentStatus(StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"


class ConsentScope(StrEnum):
    """Purposes a participant can consent to. Checked before each kind of processing."""

    CONVERSATION = "conversation"
    CONTEXT_PROJECTION = "context_projection"
    EVIDENCE = "evidence"
    REPORTING = "reporting"


class RetentionClass(StrEnum):
    DELETE_ON_REVOCATION = "delete_on_revocation"
    RETAIN_FOR_AUDIT = "retain_for_audit"
    STANDARD = "standard"


class RelationshipType(StrEnum):
    MENTOR = "mentor"
    CLINICIAN = "clinician"
    CAREGIVER = "caregiver"
    COACH = "coach"
    RESEARCHER = "researcher"
