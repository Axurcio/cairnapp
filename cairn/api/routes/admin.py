"""Tenant and participant administration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from cairn.api.deps import get_access, get_actor, get_repos, get_request_id
from cairn.api.schemas import ParticipantCreate, ParticipantOut, TenantCreate, TenantOut
from cairn.auth.access import AccessService
from cairn.auth.context import ActorContext
from cairn.auth.decisions import Action, ResourceRef
from cairn.domain.models import Participant, Tenant
from cairn.persistence.repositories import Repositories

router = APIRouter(prefix="/v1", tags=["admin"])


@router.post("/tenants", status_code=status.HTTP_201_CREATED, response_model=TenantOut)
async def create_tenant(
    body: TenantCreate,
    actor: ActorContext = Depends(get_actor),
    repos: Repositories = Depends(get_repos),
    access: AccessService = Depends(get_access),
    request_id: str | None = Depends(get_request_id),
) -> Tenant:
    await access.authorize(actor, Action.TENANT_CREATE, ResourceRef(kind="tenant"))
    tenant = await repos.tenants.add(Tenant(name=body.name))
    await repos.audit.record(
        tenant_id=tenant.id,
        actor_id=actor.actor_id,
        action=Action.TENANT_CREATE.value,
        resource_type="tenant",
        resource_id=tenant.id,
        outcome="completed",
        request_id=request_id,
    )
    await repos.session.commit()
    return tenant


@router.post("/participants", status_code=status.HTTP_201_CREATED, response_model=ParticipantOut)
async def create_participant(
    body: ParticipantCreate,
    actor: ActorContext = Depends(get_actor),
    repos: Repositories = Depends(get_repos),
    access: AccessService = Depends(get_access),
) -> Participant:
    tenant_id = access.require_tenant(actor)
    await access.authorize(
        actor,
        Action.PARTICIPANT_CREATE,
        ResourceRef(kind="participant", tenant_id=tenant_id),
        audit=True,
    )
    participant = await repos.participants.add(
        Participant(
            tenant_id=tenant_id,
            display_name=body.display_name,
            external_ref=body.external_ref,
            is_synthetic=body.is_synthetic,
        )
    )
    await repos.session.commit()
    return participant
