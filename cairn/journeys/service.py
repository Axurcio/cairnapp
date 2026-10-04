"""Journey lifecycle: creation (with consents) and consent revocation."""

from __future__ import annotations

from uuid import UUID

from cairn.auth.access import AccessService
from cairn.auth.context import ActorContext, Role
from cairn.auth.decisions import Action, ResourceRef
from cairn.domain.enums import ActorType, ConsentScope, EventType, JourneyStatus
from cairn.domain.models import Consent, Journey, ParticipantEvent
from cairn.domain_packs.registry import DomainPackRegistry
from cairn.journeys.errors import InvalidRequest, JourneyNotActive
from cairn.persistence.repositories import Repositories
from cairn.workflows.dispatcher import WorkflowDispatcher
from cairn.workflows.types import ConsentRevocationInput, JourneyWorkflowInput


class JourneyService:
    def __init__(
        self,
        repos: Repositories,
        access: AccessService,
        packs: DomainPackRegistry,
        dispatcher: WorkflowDispatcher,
        *,
        request_id: str | None = None,
    ) -> None:
        self._repos = repos
        self._access = access
        self._packs = packs
        self._dispatcher = dispatcher
        self._request_id = request_id

    async def create(
        self,
        actor: ActorContext,
        *,
        participant_id: UUID,
        domain_pack: str,
        title: str,
        consent_scopes: list[ConsentScope],
        is_synthetic: bool = False,
        source: str = "api",
    ) -> Journey:
        participant = await self._access.participant(actor, participant_id, Action.JOURNEY_CREATE)
        pack = self._packs.get(domain_pack)
        journey = await self._repos.journeys.add(
            Journey(
                tenant_id=participant.tenant_id,
                participant_id=participant.id,
                title=title,
                domain_pack=pack.id,
                domain_pack_version=pack.version,
                status=JourneyStatus.ACTIVE,
                is_synthetic=is_synthetic or participant.is_synthetic,
            )
        )
        for scope in dict.fromkeys(consent_scopes):
            await self._repos.consents.add(
                Consent(
                    tenant_id=journey.tenant_id,
                    participant_id=participant.id,
                    journey_id=journey.id,
                    scope=scope,
                    source=source,
                )
            )
        await self._repos.audit.record(
            tenant_id=journey.tenant_id,
            actor_id=actor.actor_id,
            action="journey:create",
            resource_type="journey",
            resource_id=journey.id,
            outcome="completed",
            details={
                "domain_pack": pack.id,
                "domain_pack_version": pack.version,
                "consents": [s.value for s in consent_scopes],
            },
            request_id=self._request_id,
        )
        await self._repos.session.commit()
        await self._dispatcher.journey_started(
            JourneyWorkflowInput(
                tenant_id=str(journey.tenant_id),
                journey_id=str(journey.id),
                follow_up_hours=pack.planner.follow_up_after_hours,
            )
        )
        return journey

    async def list_visible(self, actor: ActorContext) -> list[Journey]:
        """Journeys this actor may read, newest first.

        Candidates mirror the CairnPolicyDecisionProvider rules: tenant admins see the
        whole tenant, participants their own journeys, facilitators the journeys covered
        by an active relationship.
        """
        tenant_id = self._access.require_tenant(actor)
        await self._access.authorize(
            actor, Action.JOURNEY_READ, ResourceRef(kind="journey", tenant_id=tenant_id), audit=True
        )
        if actor.has_role(Role.TENANT_ADMIN):
            journeys = await self._repos.journeys.list_for_tenant(tenant_id)
        else:
            found: dict[UUID, Journey] = {}
            if actor.has_role(Role.PARTICIPANT) and actor.participant_id is not None:
                for j in await self._repos.journeys.list_for_participant(
                    tenant_id, actor.participant_id
                ):
                    found[j.id] = j
            if actor.has_role(Role.FACILITATOR):
                for rel in await self._repos.relationships.list_active_for_actor(
                    tenant_id, actor.actor_id
                ):
                    for j in await self._repos.journeys.list_for_participant(
                        tenant_id, rel.participant_id
                    ):
                        if rel.journey_id is None or rel.journey_id == j.id:
                            found[j.id] = j
            journeys = sorted(found.values(), key=lambda j: j.started_at, reverse=True)
        await self._repos.session.commit()
        return journeys

    async def revoke_consent(
        self, actor: ActorContext, journey_id: UUID, scopes: list[ConsentScope]
    ) -> str:
        if not scopes:
            raise InvalidRequest("at least one scope is required")
        journey = await self._access.journey(actor, journey_id, Action.CONSENT_REVOKE, audit=True)
        if journey.status is JourneyStatus.CLOSED:
            raise JourneyNotActive("journey is closed")
        # Step 1 happens synchronously so no further processing can start under the old
        # consent; the workflow then propagates the revocation to derived stores.
        revoked = await self._repos.consents.revoke(journey.tenant_id, journey.id, scopes)
        await self._repos.events.append(
            ParticipantEvent(
                tenant_id=journey.tenant_id,
                journey_id=journey.id,
                participant_id=journey.participant_id,
                event_type=EventType.CONSENT_REVOKED,
                actor_type=ActorType.SYSTEM,
                source="api",
                payload={"scopes": [s.value for s in scopes], "requested_by": actor.actor_id},
            )
        )
        await self._repos.session.commit()
        return await self._dispatcher.revoke_consent(
            ConsentRevocationInput(
                tenant_id=str(journey.tenant_id),
                journey_id=str(journey.id),
                scopes=[s.value for s in scopes],
                requested_by=actor.actor_id,
                consent_ids=[str(c.id) for c in revoked],
                request_id=self._request_id,
            )
        )
