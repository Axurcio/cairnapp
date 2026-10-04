"""The authenticated actor, as seen by every request."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"
    FACILITATOR = "facilitator"
    PARTICIPANT = "participant"


class ActorContext(BaseModel):
    actor_id: str
    # The tenant always comes from authentication, never from a request body.
    tenant_id: UUID | None
    participant_id: UUID | None = None
    roles: frozenset[Role] = Field(default_factory=frozenset)
    scopes: frozenset[str] | None = None  # None = role defaults; a set restricts further

    def has_role(self, role: Role) -> bool:
        return role in self.roles


class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
