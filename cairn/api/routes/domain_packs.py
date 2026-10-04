"""Read-only Domain Pack catalogue."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cairn.api.deps import get_actor, get_container
from cairn.api.schemas import DomainPackDetail, DomainPackSummary
from cairn.auth.context import ActorContext, AuthorizationError
from cairn.auth.decisions import ROLE_ACTIONS, Action
from cairn.container import Container
from cairn.domain_packs.pack import DomainPack

router = APIRouter(prefix="/v1/domain-packs", tags=["domain-packs"])


def _require_read(actor: ActorContext) -> None:
    if not any(Action.DOMAIN_PACK_READ in ROLE_ACTIONS[r] for r in actor.roles):
        raise AuthorizationError("no role grants domain_pack:read")


def _summary(pack: DomainPack) -> DomainPackSummary:
    m = pack.manifest
    return DomainPackSummary(
        id=m.id,
        name=m.name,
        version=m.version,
        classification=m.classification,
        regulatory_profile=m.regulatory_profile,
        synthetic_sample=m.synthetic_sample,
        description=m.description,
    )


@router.get("", response_model=list[DomainPackSummary])
async def list_domain_packs(
    actor: ActorContext = Depends(get_actor),
    container: Container = Depends(get_container),
) -> list[DomainPackSummary]:
    _require_read(actor)
    return [_summary(p) for p in container.packs.all()]


@router.get("/{pack_id}", response_model=DomainPackDetail)
async def get_domain_pack(
    pack_id: str,
    actor: ActorContext = Depends(get_actor),
    container: Container = Depends(get_container),
) -> DomainPackDetail:
    _require_read(actor)
    pack = container.packs.get(pack_id)
    return DomainPackDetail(
        **_summary(pack).model_dump(),
        checksum=pack.checksum,
        terminology=pack.manifest.terminology,
        observation_types={
            s.observation_type: {
                "version": s.version,
                "description": s.description,
                "fields": {n: f.type.value for n, f in s.fields.items()},
            }
            for s in pack.observation_schemas.values()
        },
        response_policies=[
            {
                "id": p.id,
                "version": p.version,
                "trigger": p.trigger.observation_type,
                "required_fields": [r.field for r in p.required_fields],
                "priority": p.priority,
                "completion": p.completion.action.value,
            }
            for p in pack.response_policies
        ],
        question_protocols=[
            {"id": q.id, "version": q.version, "questions": [x.id for x in q.questions]}
            for q in pack.question_protocols
        ],
        patterns=[
            {
                "id": r.id,
                "version": r.version,
                "algorithm": r.algorithm,
                "observation_type": r.observation_type,
            }
            for r in pack.patterns
        ],
        activities=sorted(pack.activities),
        safety_policy={"id": pack.safety.id, "version": pack.safety.version},
        planner_version=pack.planner.version,
        report_templates=sorted(pack.reports),
    )
