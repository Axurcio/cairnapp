"""PolicyDecisionProvider: application authorization decisions.

:class:`CairnPolicyDecisionProvider` is the in-process implementation used today.
The protocol leaves room for an ``OPAPolicyDecisionProvider`` (calling an OPA
sidecar with the same :class:`AuthzRequest`) without changing callers; OPA is
not a dependency of the MVP.

Rules (evaluated in order):

1. Tenant boundary - the resource tenant must equal the actor tenant. Always.
2. Role must grant the action (and the optional scope restriction must allow it).
3. Relationship rules - participants only reach their own data; facilitators only
   reach participants they have an active relationship with.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from cairn.auth.context import ActorContext, Role


class Action(StrEnum):
    TENANT_CREATE = "tenant:create"
    PARTICIPANT_CREATE = "participant:create"
    PARTICIPANT_READ = "participant:read"
    JOURNEY_CREATE = "journey:create"
    JOURNEY_READ = "journey:read"
    JOURNEY_MESSAGE = "journey:message"
    EVIDENCE_WRITE = "evidence:write"
    EVIDENCE_READ = "evidence:read"
    CONTEXT_REBUILD = "context:rebuild"
    CONSENT_REVOKE = "consent:revoke"
    REPORT_READ = "report:read"
    DOMAIN_PACK_READ = "domain_pack:read"


ROLE_ACTIONS: dict[Role, frozenset[Action]] = {
    Role.PLATFORM_ADMIN: frozenset({Action.TENANT_CREATE, Action.DOMAIN_PACK_READ}),
    Role.TENANT_ADMIN: frozenset(
        {
            Action.PARTICIPANT_CREATE,
            Action.PARTICIPANT_READ,
            Action.JOURNEY_CREATE,
            Action.JOURNEY_READ,
            Action.EVIDENCE_READ,
            Action.CONTEXT_REBUILD,
            Action.CONSENT_REVOKE,
            Action.REPORT_READ,
            Action.DOMAIN_PACK_READ,
        }
    ),
    Role.FACILITATOR: frozenset(
        {
            Action.PARTICIPANT_READ,
            Action.JOURNEY_READ,
            Action.EVIDENCE_READ,
            Action.REPORT_READ,
            Action.DOMAIN_PACK_READ,
        }
    ),
    Role.PARTICIPANT: frozenset(
        {
            Action.JOURNEY_READ,
            Action.JOURNEY_MESSAGE,
            Action.EVIDENCE_WRITE,
            Action.EVIDENCE_READ,
            Action.CONSENT_REVOKE,
            Action.REPORT_READ,
            Action.DOMAIN_PACK_READ,
        }
    ),
}


class ResourceRef(BaseModel):
    kind: str
    tenant_id: UUID | None = None
    participant_id: UUID | None = None
    journey_id: UUID | None = None
    resource_id: UUID | None = None


class AuthzRequest(BaseModel):
    actor: ActorContext
    action: Action
    resource: ResourceRef
    # Pre-resolved facts from canonical data (never from a context projection).
    has_relationship: bool = False


class AuthzDecision(BaseModel):
    allowed: bool
    reason: str
    provider: str


class PolicyDecisionProvider(Protocol):
    name: str

    async def decide(self, request: AuthzRequest) -> AuthzDecision: ...


class CairnPolicyDecisionProvider:
    name = "cairn"

    async def decide(self, request: AuthzRequest) -> AuthzDecision:
        actor, action, res = request.actor, request.action, request.resource

        def deny(reason: str) -> AuthzDecision:
            return AuthzDecision(allowed=False, reason=reason, provider=self.name)

        if res.tenant_id is not None and res.tenant_id != actor.tenant_id:
            return deny("tenant boundary")
        granting = [r for r in actor.roles if action in ROLE_ACTIONS.get(r, frozenset())]
        if not granting:
            return deny(f"no role grants {action}")
        if actor.scopes is not None and action.value not in actor.scopes:
            return deny(f"scope {action} not granted to this credential")

        def allow(reason: str) -> AuthzDecision:
            return AuthzDecision(allowed=True, reason=reason, provider=self.name)

        if Role.PLATFORM_ADMIN in granting or Role.TENANT_ADMIN in granting:
            return allow("administrative role")
        own = res.participant_id is None or res.participant_id == actor.participant_id
        if Role.PARTICIPANT in granting and own:
            return allow("own data")
        if Role.FACILITATOR in granting and (
            res.participant_id is None or request.has_relationship
        ):
            return allow("active relationship")
        return deny("not the participant and no active relationship")
