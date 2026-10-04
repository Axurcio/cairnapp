"""Access checks for tenant, journey, participant and evidence resources.

Loads the resource *within the actor's tenant* first (so other tenants' ids are
simply "not found", preventing IDOR/existence leaks), resolves relationship facts
from canonical data, asks the PolicyDecisionProvider, and audits the outcome.
"""

from __future__ import annotations

from uuid import UUID

from cairn.auth.context import ActorContext, AuthorizationError
from cairn.auth.decisions import Action, AuthzRequest, PolicyDecisionProvider, ResourceRef
from cairn.domain.models import Journey, Participant
from cairn.persistence.repositories import Repositories


class NotFound(LookupError):
    pass


class AccessService:
    def __init__(
        self,
        repos: Repositories,
        decisions: PolicyDecisionProvider,
        *,
        request_id: str | None = None,
    ) -> None:
        self._repos = repos
        self._decisions = decisions
        self._request_id = request_id

    @staticmethod
    def require_tenant(actor: ActorContext) -> UUID:
        if actor.tenant_id is None:
            raise AuthorizationError("a tenant-scoped credential is required")
        return actor.tenant_id

    async def authorize(
        self, actor: ActorContext, action: Action, resource: ResourceRef, *, audit: bool = False
    ) -> None:
        has_relationship = False
        if resource.participant_id is not None and actor.tenant_id is not None:
            has_relationship = await self._repos.relationships.has_active(
                actor.tenant_id, actor.actor_id, resource.participant_id, resource.journey_id
            )
        decision = await self._decisions.decide(
            AuthzRequest(
                actor=actor,
                action=action,
                resource=resource,
                has_relationship=has_relationship,
            )
        )
        if audit or not decision.allowed:
            await self._repos.audit.record(
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                action=action.value,
                resource_type=resource.kind,
                resource_id=resource.resource_id or resource.journey_id,
                outcome="allowed" if decision.allowed else "denied",
                details={"reason": decision.reason, "provider": decision.provider},
                request_id=self._request_id,
            )
        if not decision.allowed:
            # Persist the denial even though the request fails. Authorization always runs
            # before a request writes anything, so this commits only the audit row.
            await self._repos.session.commit()
            raise AuthorizationError(decision.reason)

    async def journey(
        self, actor: ActorContext, journey_id: UUID, action: Action, *, audit: bool = False
    ) -> Journey:
        tenant_id = self.require_tenant(actor)
        journey = await self._repos.journeys.get(tenant_id, journey_id)
        if journey is None:
            raise NotFound("journey")
        await self.authorize(
            actor,
            action,
            ResourceRef(
                kind="journey",
                tenant_id=journey.tenant_id,
                participant_id=journey.participant_id,
                journey_id=journey.id,
                resource_id=journey.id,
            ),
            audit=audit,
        )
        return journey

    async def participant(
        self, actor: ActorContext, participant_id: UUID, action: Action
    ) -> Participant:
        tenant_id = self.require_tenant(actor)
        participant = await self._repos.participants.get(tenant_id, participant_id)
        if participant is None:
            raise NotFound("participant")
        await self.authorize(
            actor,
            action,
            ResourceRef(
                kind="participant",
                tenant_id=participant.tenant_id,
                participant_id=participant.id,
                resource_id=participant.id,
            ),
        )
        return participant
