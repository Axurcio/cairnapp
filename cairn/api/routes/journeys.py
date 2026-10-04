"""Journey endpoints. Tenant always comes from the authenticated actor."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from cairn.api.deps import (
    get_access,
    get_actor,
    get_container,
    get_journey_service,
    get_message_service,
    get_repos,
    get_request_id,
)
from cairn.api.schemas import (
    ConsentRevokeRequest,
    ConsentsOut,
    EvidenceOut,
    JourneyCreate,
    JourneyOut,
    JourneySummaryOut,
    MessageCreate,
    MessageExplanation,
    MessageResponse,
    NextActionOut,
    ObservationOut,
    PatternEvaluationOut,
    StatusOut,
    TimelineEntry,
)
from cairn.auth.access import AccessService
from cairn.auth.context import ActorContext
from cairn.auth.decisions import Action
from cairn.container import Container
from cairn.domain.enums import (
    ActorType,
    ConsentScope,
    EventType,
    JourneyStatus,
    NextActionStatus,
    RetentionClass,
)
from cairn.domain.models import Evidence, Journey, ParticipantEvent, Provenance, Report
from cairn.evidence.validation import validate_upload
from cairn.journeys.errors import ConsentRequired, JourneyNotActive
from cairn.journeys.message_service import JourneyMessageService
from cairn.journeys.service import JourneyService
from cairn.persistence.repositories import Repositories
from cairn.reporting.service import build_report
from cairn.workflows.types import JourneyRef

router = APIRouter(prefix="/v1/journeys", tags=["journeys"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=JourneyOut)
async def create_journey(
    body: JourneyCreate,
    actor: ActorContext = Depends(get_actor),
    service: JourneyService = Depends(get_journey_service),
) -> Journey:
    return await service.create(
        actor,
        participant_id=body.participant_id,
        domain_pack=body.domain_pack,
        title=body.title,
        consent_scopes=body.consents,
        is_synthetic=body.is_synthetic,
    )


@router.get("", response_model=list[JourneySummaryOut])
async def list_journeys(
    actor: ActorContext = Depends(get_actor),
    service: JourneyService = Depends(get_journey_service),
    repos: Repositories = Depends(get_repos),
    container: Container = Depends(get_container),
) -> list[JourneySummaryOut]:
    journeys = await service.list_visible(actor)
    if not journeys:
        return []
    tenant_id = journeys[0].tenant_id
    participants = {
        p.id: p
        for p in await repos.participants.get_many(
            tenant_id, list({j.participant_id for j in journeys})
        )
    }
    pack_names = {p.id: p.manifest.name for p in container.packs.all()}
    return [
        JourneySummaryOut(
            **JourneyOut.model_validate(j).model_dump(),
            participant_display_name=(
                participants[j.participant_id].display_name
                if j.participant_id in participants
                else None
            ),
            domain_pack_name=pack_names.get(j.domain_pack),
        )
        for j in journeys
    ]


@router.get("/{journey_id}", response_model=JourneyOut)
async def get_journey(
    journey_id: UUID,
    actor: ActorContext = Depends(get_actor),
    access: AccessService = Depends(get_access),
    repos: Repositories = Depends(get_repos),
) -> Journey:
    journey = await access.journey(actor, journey_id, Action.JOURNEY_READ, audit=True)
    await repos.session.commit()
    return journey


@router.post("/{journey_id}/messages", response_model=MessageResponse)
async def post_message(
    journey_id: UUID,
    body: MessageCreate,
    actor: ActorContext = Depends(get_actor),
    service: JourneyMessageService = Depends(get_message_service),
) -> MessageResponse:
    result = await service.handle(actor, journey_id, body.text, occurred_at=body.occurred_at)
    return MessageResponse(
        journey_id=result.journey_id,
        participant_event_id=result.participant_event_id,
        assistant_event_id=result.assistant_event_id,
        response=result.rendered,
        next_action=NextActionOut.model_validate(result.next_action),
        observation=ObservationOut.model_validate(result.observation)
        if result.observation
        else None,
        pattern_evaluations=[
            PatternEvaluationOut.model_validate(e) for e in result.pattern_evaluations
        ],
        explanation=MessageExplanation(
            policy_decision=result.policy_decision,
            planner_decision=result.planner_decision,
            intent=result.intent,
            extraction=result.extraction,
            safety=result.safety,
            guardrails=result.guardrails,
            context=result.context,
            trace=result.trace,
        ),
    )


def _timeline_entry(event: ParticipantEvent) -> TimelineEntry:
    payload: dict[str, Any] = event.payload
    text = payload.get("text") if isinstance(payload.get("text"), str) else None
    details = {k: v for k, v in payload.items() if k not in ("text", "intent")}
    return TimelineEntry(
        event_id=event.id,
        event_type=event.event_type,
        actor_type=event.actor_type,
        occurred_at=event.occurred_at,
        source=event.source,
        text=text,
        evidence_refs=event.evidence_refs,
        details=details,
    )


@router.get("/{journey_id}/timeline", response_model=list[TimelineEntry])
async def get_timeline(
    journey_id: UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    actor: ActorContext = Depends(get_actor),
    access: AccessService = Depends(get_access),
    repos: Repositories = Depends(get_repos),
) -> list[TimelineEntry]:
    journey = await access.journey(actor, journey_id, Action.JOURNEY_READ, audit=True)
    events = await repos.events.list_for_journey(journey.tenant_id, journey.id, limit=limit)
    await repos.session.commit()
    return [_timeline_entry(e) for e in events]


@router.get("/{journey_id}/observations", response_model=list[ObservationOut])
async def get_observations(
    journey_id: UUID,
    observation_type: str | None = None,
    actor: ActorContext = Depends(get_actor),
    access: AccessService = Depends(get_access),
    repos: Repositories = Depends(get_repos),
) -> list[ObservationOut]:
    journey = await access.journey(actor, journey_id, Action.JOURNEY_READ, audit=True)
    observations = await repos.observations.list_for_journey(
        journey.tenant_id, journey.id, observation_type=observation_type
    )
    await repos.session.commit()
    return [ObservationOut.model_validate(o) for o in observations]


@router.get("/{journey_id}/next-actions", response_model=list[NextActionOut])
async def get_next_actions(
    journey_id: UUID,
    status_filter: NextActionStatus | None = Query(default=None, alias="status"),
    actor: ActorContext = Depends(get_actor),
    access: AccessService = Depends(get_access),
    repos: Repositories = Depends(get_repos),
) -> list[NextActionOut]:
    journey = await access.journey(actor, journey_id, Action.JOURNEY_READ)
    actions = await repos.next_actions.list_for_journey(
        journey.tenant_id, journey.id, status=status_filter
    )
    return [NextActionOut.model_validate(a) for a in actions]


@router.post(
    "/{journey_id}/evidence", status_code=status.HTTP_201_CREATED, response_model=EvidenceOut
)
async def upload_evidence(
    journey_id: UUID,
    file: UploadFile = File(...),
    capture_type: str = Form(default="upload", max_length=64, pattern=r"^[a-z_]+$"),
    retention_class: RetentionClass = Form(default=RetentionClass.STANDARD),
    actor: ActorContext = Depends(get_actor),
    access: AccessService = Depends(get_access),
    repos: Repositories = Depends(get_repos),
    container: Container = Depends(get_container),
) -> EvidenceOut:
    journey = await access.journey(actor, journey_id, Action.EVIDENCE_WRITE, audit=True)
    if journey.status is not JourneyStatus.ACTIVE:
        raise JourneyNotActive(f"journey is {journey.status}")
    scopes = await repos.consents.granted_scopes(
        journey.tenant_id, journey.participant_id, journey.id
    )
    if ConsentScope.EVIDENCE not in scopes:
        raise ConsentRequired("evidence consent has not been granted")

    settings = container.settings
    data = await file.read(settings.max_upload_bytes + 1)
    content_type = (file.content_type or "application/octet-stream").split(";")[0].lower()
    checksum = validate_upload(
        data,
        content_type,
        allowed=settings.allowed_evidence_content_types,
        max_bytes=settings.max_upload_bytes,
    )
    evidence_id, event_id = uuid4(), uuid4()
    # Object keys never contain client-supplied names.
    object_key = f"{journey.tenant_id}/{journey.id}/{evidence_id}"
    await container.evidence_store.put(object_key, data, content_type)

    evidence = await repos.evidence.add(
        Evidence(
            id=evidence_id,
            tenant_id=journey.tenant_id,
            journey_id=journey.id,
            participant_id=journey.participant_id,
            source="api",
            content_type=content_type,
            capture_type=capture_type,
            size_bytes=len(data),
            checksum_sha256=checksum,
            object_key=object_key,
            retention_class=retention_class,
            domain_pack=journey.domain_pack,
            domain_pack_version=journey.domain_pack_version,
            provenance=Provenance(
                source_event_ids=(event_id,),
                produced_by="api:evidence_upload",
                domain_pack=journey.domain_pack,
                domain_pack_version=journey.domain_pack_version,
            ),
        )
    )
    await repos.events.append(
        ParticipantEvent(
            id=event_id,
            tenant_id=journey.tenant_id,
            journey_id=journey.id,
            participant_id=journey.participant_id,
            event_type=EventType.EVIDENCE_ADDED,
            actor_type=ActorType.PARTICIPANT,
            source="api",
            consent_scope=ConsentScope.EVIDENCE,
            evidence_refs=[evidence.id],
            domain_pack=journey.domain_pack,
            domain_pack_version=journey.domain_pack_version,
            payload={
                "capture_type": capture_type,
                "content_type": content_type,
                "size_bytes": len(data),
            },
        )
    )
    await repos.session.commit()
    return EvidenceOut(
        **EvidenceOut.model_validate(evidence).model_dump(exclude={"event_id"}), event_id=event_id
    )


@router.post(
    "/{journey_id}/context/rebuild", status_code=status.HTTP_202_ACCEPTED, response_model=StatusOut
)
async def rebuild_context(
    journey_id: UUID,
    actor: ActorContext = Depends(get_actor),
    access: AccessService = Depends(get_access),
    repos: Repositories = Depends(get_repos),
    container: Container = Depends(get_container),
) -> StatusOut:
    journey = await access.journey(actor, journey_id, Action.CONTEXT_REBUILD, audit=True)
    await repos.session.commit()
    outcome = await container.dispatcher.rebuild_context(
        JourneyRef(tenant_id=str(journey.tenant_id), journey_id=str(journey.id))
    )
    return StatusOut(status=outcome)


@router.get("/{journey_id}/report", response_model=Report)
async def get_report(
    journey_id: UUID,
    actor: ActorContext = Depends(get_actor),
    access: AccessService = Depends(get_access),
    repos: Repositories = Depends(get_repos),
    container: Container = Depends(get_container),
) -> Report:
    journey = await access.journey(actor, journey_id, Action.REPORT_READ, audit=True)
    pack = container.packs.resolve_for_journey(journey.domain_pack, journey.domain_pack_version)
    observations = await repos.observations.list_for_journey(journey.tenant_id, journey.id)
    await repos.session.commit()
    return build_report(pack, journey, observations)


@router.get("/{journey_id}/consents", response_model=ConsentsOut)
async def get_consents(
    journey_id: UUID,
    actor: ActorContext = Depends(get_actor),
    access: AccessService = Depends(get_access),
    repos: Repositories = Depends(get_repos),
) -> ConsentsOut:
    journey = await access.journey(actor, journey_id, Action.JOURNEY_READ)
    granted = await repos.consents.granted_scopes(
        journey.tenant_id, journey.participant_id, journey.id
    )
    return ConsentsOut(granted=sorted(granted))


@router.post(
    "/{journey_id}/consent/revoke", status_code=status.HTTP_202_ACCEPTED, response_model=StatusOut
)
async def revoke_consent(
    journey_id: UUID,
    body: ConsentRevokeRequest,
    actor: ActorContext = Depends(get_actor),
    service: JourneyService = Depends(get_journey_service),
    request_id: str | None = Depends(get_request_id),
) -> StatusOut:
    return StatusOut(status=await service.revoke_consent(actor, journey_id, body.scopes))
