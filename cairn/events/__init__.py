"""The canonical, append-only journey event log.

Events record what actually happened (a participant message, an assistant reply,
evidence added, consent revoked...). They are the root of provenance: Observations,
NextActions, PatternEvaluations, reports and context projections all reference
event ids. Events are never updated or deleted by application code; the repository
exposes ``append`` and reads only.
"""

from cairn.domain.enums import ActorType, EventType
from cairn.domain.models import ParticipantEvent
from cairn.persistence.repositories import EventRepository

__all__ = ["ActorType", "EventRepository", "EventType", "ParticipantEvent"]
