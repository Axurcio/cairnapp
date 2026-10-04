"""Journey message orchestration - one participant turn, step by step.

This is deliberately NOT a generic ``agent.run()``. Each step is an explicit call
whose output is inspectable, logged and returned in :class:`MessageTurnResult`::

    authenticate (API) -> load journey + authorize + consent check
    -> load Domain Pack -> persist raw participant event
    -> safety input assessment + guardrail input check
    -> recall derived context (optional, consented)
    -> AI extraction -> schema validation -> update structured Observation
    -> evaluate patterns -> evaluate ResponsePolicy -> Planner selects NextAction
    -> SafetyPolicy validation -> ResponseIntent -> render
    -> output validation (SafetyPolicy + guardrails) -> persist NextAction + assistant event
    -> queue context projection -> notify journey workflow -> return

The LLM (if any) only extracts and phrases. Every decision is deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cairn.ai.extraction import ExtractionResult, ExtractionService
from cairn.ai.provider import ExtractionRequest, PendingQuestionContext
from cairn.ai.rendering import RenderedResponse, ResponseRenderer, deterministic_text
from cairn.auth.access import AccessService
from cairn.auth.context import ActorContext
from cairn.auth.decisions import Action
from cairn.context.provider import ContextItem, ContextMemoryProvider, ContextScope
from cairn.domain.enums import (
    ActorType,
    ConsentScope,
    EventType,
    JourneyStatus,
    NextActionStatus,
    NextActionType,
    ObservationStatus,
)
from cairn.domain.models import (
    NextAction,
    Observation,
    ParticipantEvent,
    PatternEvaluation,
    utcnow,
)
from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.registry import DomainPackRegistry
from cairn.domain_packs.schemas import ResponsePolicy
from cairn.guardrails.provider import GuardrailCheck, GuardrailContext, GuardrailProvider
from cairn.journeys.errors import ConsentRequired, InvalidRequest, JourneyNotActive
from cairn.observability.logging import bind_context, get_logger
from cairn.observability.tracing import get_tracer
from cairn.patterns.engine import PatternEngine
from cairn.persistence.repositories import Repositories
from cairn.planner.intents import ResponseIntent, build_response_intent
from cairn.planner.planner import ActivityRecord, Planner, PlannerDecision, PlannerInput
from cairn.policies.response_policy import (
    AskRecord,
    PolicyAction,
    PolicyDecision,
    ResponsePolicyEngine,
)
from cairn.policies.safety import SafetyPolicyValidator, SafetyViolation
from cairn.workflows.dispatcher import WorkflowDispatcher
from cairn.workflows.types import JourneyWorkflowInput, ProjectionRequest

log = get_logger(__name__)
tracer = get_tracer(__name__)

MAX_MESSAGE_CHARS = 4000
MAX_CLOCK_SKEW = timedelta(minutes=5)


class ExtractionSummary(BaseModel):
    provider: str
    model: str
    extraction_version: str
    attempts: int
    errors: list[str]
    new_observation_types: list[str]
    answered_field: str | None
    declined: bool


class SafetySummary(BaseModel):
    input_signal: str | None = None
    decision_violations: list[SafetyViolation] = Field(default_factory=list)
    intent_violations: list[SafetyViolation] = Field(default_factory=list)
    output_violations: list[SafetyViolation] = Field(default_factory=list)
    fallback_applied: bool = False


class ContextSummary(BaseModel):
    provider: str
    recalled_items: int
    recall_error: str | None = None
    projection: str


class MessageTurnResult(BaseModel):
    journey_id: UUID
    participant_event_id: UUID
    assistant_event_id: UUID
    response_text: str
    rendered: RenderedResponse
    intent: ResponseIntent
    next_action: NextAction
    planner_decision: PlannerDecision
    policy_decision: PolicyDecision | None
    observation: Observation | None
    pattern_evaluations: list[PatternEvaluation]
    extraction: ExtractionSummary | None
    safety: SafetySummary
    guardrails: list[GuardrailCheck]
    context: ContextSummary
    trace: list[str]


class JourneyMessageService:
    def __init__(
        self,
        *,
        repos: Repositories,
        access: AccessService,
        packs: DomainPackRegistry,
        extraction: ExtractionService,
        renderer: ResponseRenderer,
        guardrails: GuardrailProvider,
        context: ContextMemoryProvider,
        dispatcher: WorkflowDispatcher,
    ) -> None:
        self._repos = repos
        self._access = access
        self._packs = packs
        self._extraction = extraction
        self._renderer = renderer
        self._guardrails = guardrails
        self._context = context
        self._dispatcher = dispatcher
        self._policies = ResponsePolicyEngine()
        self._patterns = PatternEngine()
        self._planner = Planner()

    async def handle(
        self,
        actor: ActorContext,
        journey_id: UUID,
        text: str,
        *,
        occurred_at: datetime | None = None,
        source: str = "api",
    ) -> MessageTurnResult:
        with tracer.start_as_current_span("journey.message"):
            return await self._handle(
                actor, journey_id, text, occurred_at=occurred_at, source=source
            )

    async def _handle(
        self,
        actor: ActorContext,
        journey_id: UUID,
        text: str,
        *,
        occurred_at: datetime | None,
        source: str,
    ) -> MessageTurnResult:
        trace: list[str] = []
        text = text.strip()
        if not text or len(text) > MAX_MESSAGE_CHARS:
            raise InvalidRequest(f"message must be 1..{MAX_MESSAGE_CHARS} characters")
        now = utcnow()
        turn_time = occurred_at or now
        if turn_time > now + MAX_CLOCK_SKEW:
            raise InvalidRequest("occurred_at must not be in the future")

        # -- load journey, authorize, check consent ---------------------------
        journey = await self._access.journey(actor, journey_id, Action.JOURNEY_MESSAGE)
        bind_context(tenant_id=journey.tenant_id, journey_id=journey.id)
        if journey.status is not JourneyStatus.ACTIVE:
            raise JourneyNotActive(f"journey is {journey.status}")
        consents = await self._repos.consents.granted_scopes(
            journey.tenant_id, journey.participant_id, journey.id
        )
        if ConsentScope.CONVERSATION not in consents:
            raise ConsentRequired("conversation consent has not been granted")
        trace.append("journey.loaded")

        # -- load Domain Pack ------------------------------------------------
        pack = self._packs.resolve_for_journey(journey.domain_pack, journey.domain_pack_version)
        pack_ref = {"domain_pack": pack.id, "domain_pack_version": pack.version}
        trace.append(f"domain_pack.loaded:{pack.id}@{pack.version}")

        # -- persist raw participant event (committed before any AI call) ----
        p_event = await self._repos.events.append(
            ParticipantEvent(
                tenant_id=journey.tenant_id,
                journey_id=journey.id,
                participant_id=journey.participant_id,
                event_type=EventType.PARTICIPANT_MESSAGE,
                actor_type=ActorType.PARTICIPANT,
                occurred_at=turn_time,
                source=source,
                payload={"text": text},
                consent_scope=ConsentScope.CONVERSATION,
                **pack_ref,
            )
        )
        await self._repos.session.commit()
        log.info("journey.message.received", event_id=str(p_event.id), chars=len(text))
        trace.append("participant_event.persisted")

        # -- safety input assessment + guardrails ----------------------------
        safety = SafetyPolicyValidator(pack)
        safety_summary = SafetySummary()
        signal = safety.assess_input(text)
        safety_summary.input_signal = signal.trigger_id if signal else None
        gctx = GuardrailContext(
            domain_pack=pack.id, domain_pack_version=pack.version, journey_id=str(journey.id)
        )
        guardrail_checks = [await self._guardrails.validate_input(text, gctx)]
        input_allowed = guardrail_checks[0].allowed
        trace.append("input.checked")

        # -- recall derived context (optional; failures never break a turn) --
        context_summary = ContextSummary(
            provider=self._context.name, recalled_items=0, projection="not_queued"
        )
        recalled: list[ContextItem] = []
        if ConsentScope.CONTEXT_PROJECTION in consents and pack.memory.recall_limit:
            try:
                recalled = await self._context.recall(
                    ContextScope(
                        tenant_id=journey.tenant_id,
                        journey_id=journey.id,
                        participant_id=journey.participant_id,
                    ),
                    text,
                    limit=pack.memory.recall_limit,
                )
            except Exception as exc:
                context_summary.recall_error = type(exc).__name__
                log.warning("context.recall.failed", error=type(exc).__name__)
            context_check = await self._guardrails.validate_context(
                [i.text for i in recalled], gctx
            )
            guardrail_checks.append(context_check)
            if not context_check.allowed:
                recalled = []
        context_summary.recalled_items = len(recalled)
        trace.append("context.recalled")

        # -- AI extraction + validation --------------------------------------
        pending = await self._repos.next_actions.pending_question(journey.tenant_id, journey.id)
        extraction: ExtractionResult | None = None
        if input_allowed and signal is None:
            extraction = await self._extraction.extract(
                pack,
                ExtractionRequest(
                    message=text,
                    domain_pack=pack.id,
                    domain_pack_version=pack.version,
                    observation_schemas=list(pack.observation_schemas.values()),
                    pending_question=self._pending_context(pack, pending),
                    context_snippets=[i.text for i in recalled],
                ),
            )
            log.info(
                "observation.extracted",
                provider=extraction.provider,
                new=len(extraction.new_observations),
                answered=extraction.answer.field if extraction.answer else None,
                errors=len(extraction.errors),
            )
            trace.append("extraction.validated")

        # -- update structured Observation -----------------------------------
        observation, is_new = await self._apply_extraction(
            pack,
            journey.tenant_id,
            journey.id,
            journey.participant_id,
            p_event,
            extraction,
            pending,
            turn_time,
        )
        trace.append("observation.updated" if observation else "observation.none")

        # -- patterns --------------------------------------------------------
        evaluations: list[PatternEvaluation] = []
        if observation is not None:
            history = await self._repos.observations.list_for_journey(
                journey.tenant_id, journey.id, observation_type=observation.observation_type
            )
            evaluations = self._patterns.evaluate(
                pack,
                observation.observation_type,
                history,
                tenant_id=journey.tenant_id,
                journey_id=journey.id,
                participant_id=journey.participant_id,
                now=turn_time,
            )
            await self._repos.patterns.add_many(evaluations)
            for e in evaluations:
                log.info(
                    "pattern.evaluated",
                    rule_id=e.rule_id,
                    rule_version=e.rule_version,
                    matched=e.matched,
                )
        trace.append("patterns.evaluated")

        # -- ResponsePolicy --------------------------------------------------
        since = turn_time - timedelta(days=1, minutes=pack.planner.session_window_minutes)
        asks = await self._repos.next_actions.history(
            journey.tenant_id, journey.id, since=since, action_types=[NextActionType.ASK_QUESTION]
        )
        ask_history = [
            AskRecord(
                question_id=a.question_id, observation_id=a.observation_id, asked_at=a.occurred_at
            )
            for a in asks
            if a.question_id
        ]
        policy: ResponsePolicy | None = None
        decision: PolicyDecision | None = None
        policy_just_completed = False
        if observation is not None and observation.status is ObservationStatus.COLLECTING:
            policy = pack.policy_for(observation.observation_type)
            if policy is not None:
                decision = self._policies.evaluate(
                    pack,
                    policy,
                    observation_type=observation.observation_type,
                    fields=observation.fields,
                    declined_fields=_declined(observation),
                    observation_id=observation.id,
                    ask_history=ask_history,
                )
                log.info(
                    "response_policy.evaluated",
                    policy_id=decision.policy_id,
                    policy_version=decision.policy_version,
                    action=decision.action,
                    question_id=decision.question_id,
                    reason=decision.reason,
                )
                if decision.action is PolicyAction.COMPLETE:
                    observation.status = ObservationStatus.COMPLETE
                    observation.updated_at = now
                    await self._repos.observations.save(observation)
                    policy_just_completed = True
        trace.append("response_policy.evaluated")

        # -- Planner ---------------------------------------------------------
        activities = await self._repos.next_actions.history(
            journey.tenant_id,
            journey.id,
            since=turn_time - timedelta(days=30),
            action_types=[NextActionType.REQUEST_ACTIVITY, NextActionType.REQUEST_EVIDENCE],
        )
        planner_decision = self._planner.plan(
            pack,
            PlannerInput(
                journey_status=journey.status,
                policy=policy,
                policy_decision=decision,
                observation_id=observation.id if observation else None,
                safety_signal=signal,
                pattern_evaluations=evaluations,
                ask_history=ask_history,
                activity_history=[
                    ActivityRecord(
                        activity_id=a.activity_id,
                        requested_at=a.occurred_at,
                        burden=pack.activities[a.activity_id].burden
                        if a.activity_id in pack.activities
                        else 0,
                    )
                    for a in activities
                    if a.activity_id
                ],
                now=turn_time,
            ),
        )
        log.info(
            "planner.action.selected",
            action=planner_decision.action_type,
            source=planner_decision.source,
            question_id=planner_decision.question_id,
            reason=planner_decision.reason,
        )
        trace.append(f"planner.selected:{planner_decision.action_type}")

        # -- SafetyPolicy on the decision ------------------------------------
        decision_check = safety.validate_decision(planner_decision)
        if not decision_check.allowed:
            safety_summary.decision_violations = decision_check.violations
            planner_decision = self._safe_fallback_decision(planner_decision)
        trace.append("safety.decision.validated")

        # -- ResponseIntent --------------------------------------------------
        intent = build_response_intent(
            pack,
            planner_decision,
            policy=policy,
            observation_fields=observation.fields if observation else {},
            is_new_observation=is_new,
            policy_just_completed=policy_just_completed,
        )
        intent_check = safety.validate_intent(intent)
        if not intent_check.allowed:
            safety_summary.intent_violations = intent_check.violations
            intent = self._safe_fallback_intent(pack, safety)
        trace.append("response_intent.built")

        # -- render + output validation --------------------------------------
        rendered = await self._renderer.render(intent)
        output_check = safety.validate_output(rendered.text)
        guard_out = await self._guardrails.validate_output(rendered.text, intent, gctx)
        guardrail_checks.append(guard_out)
        log.info(
            "guardrail.output.checked",
            provider=guard_out.provider,
            allowed=guard_out.allowed,
            safety_allowed=output_check.allowed,
        )
        if not output_check.allowed or not guard_out.allowed:
            safety_summary.output_violations = output_check.violations
            safety_summary.fallback_applied = True
            text_out = deterministic_text(intent)
            if safety.check_text(text_out):
                text_out = safety.safe_fallback_text
            rendered = RenderedResponse(
                text=text_out, renderer="template", fallback_reason="output validation failed"
            )
        trace.append("response.rendered")

        # -- persist NextAction + assistant event ----------------------------
        answered = bool(extraction and extraction.answer)
        await self._repos.next_actions.resolve_awaiting(
            journey.tenant_id,
            journey.id,
            NextActionStatus.COMPLETED if answered else NextActionStatus.SUPERSEDED,
        )
        next_action = await self._repos.next_actions.add(
            NextAction(
                tenant_id=journey.tenant_id,
                journey_id=journey.id,
                participant_id=journey.participant_id,
                action_type=planner_decision.action_type,
                status=(
                    NextActionStatus.AWAITING_REPLY
                    if planner_decision.action_type is NextActionType.ASK_QUESTION
                    else NextActionStatus.COMPLETED
                ),
                reason=planner_decision.reason,
                question_id=planner_decision.question_id,
                field=planner_decision.field,
                activity_id=planner_decision.activity_id,
                observation_id=planner_decision.observation_id,
                policy_id=planner_decision.policy_id,
                policy_version=planner_decision.policy_version,
                source_event_id=p_event.id,
                occurred_at=turn_time,
                source="planner",
                explanation={
                    "planner": planner_decision.model_dump(mode="json"),
                    "policy": decision.model_dump(mode="json") if decision else None,
                },
                **pack_ref,
            )
        )
        a_event = await self._repos.events.append(
            ParticipantEvent(
                tenant_id=journey.tenant_id,
                journey_id=journey.id,
                participant_id=journey.participant_id,
                event_type=EventType.ASSISTANT_MESSAGE,
                actor_type=ActorType.ASSISTANT,
                occurred_at=turn_time,
                source="cairn",
                consent_scope=ConsentScope.CONVERSATION,
                payload={
                    "text": rendered.text,
                    "renderer": rendered.renderer,
                    "next_action_id": str(next_action.id),
                    "intent": intent.model_dump(mode="json"),
                    "in_reply_to": str(p_event.id),
                },
                **pack_ref,
            )
        )
        await self._repos.session.commit()
        trace.append("assistant_event.persisted")

        # -- asynchronous context projection (derived; best effort) ----------
        if ConsentScope.CONTEXT_PROJECTION in consents:
            try:
                context_summary.projection = await self._dispatcher.project_events(
                    ProjectionRequest(
                        tenant_id=str(journey.tenant_id),
                        journey_id=str(journey.id),
                        event_ids=[str(p_event.id), str(a_event.id)],
                    )
                )
                log.info(
                    "context.projection.queued",
                    dispatcher=self._dispatcher.name,
                    status=context_summary.projection,
                )
            except Exception as exc:
                context_summary.projection = f"failed:{type(exc).__name__}"
                log.warning("context.projection.failed", error=type(exc).__name__)
        else:
            context_summary.projection = "skipped:no_consent"
        try:
            await self._dispatcher.participant_replied(
                JourneyWorkflowInput(
                    tenant_id=str(journey.tenant_id),
                    journey_id=str(journey.id),
                    follow_up_hours=pack.planner.follow_up_after_hours,
                ),
                str(p_event.id),
            )
        except Exception as exc:
            log.warning("journey.workflow.signal_failed", error=type(exc).__name__)
        trace.append("context.projection.queued")

        return MessageTurnResult(
            journey_id=journey.id,
            participant_event_id=p_event.id,
            assistant_event_id=a_event.id,
            response_text=rendered.text,
            rendered=rendered,
            intent=intent,
            next_action=next_action,
            planner_decision=planner_decision,
            policy_decision=decision,
            observation=observation,
            pattern_evaluations=evaluations,
            extraction=_summarise_extraction(extraction),
            safety=safety_summary,
            guardrails=guardrail_checks,
            context=context_summary,
            trace=trace,
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _pending_context(
        pack: DomainPack, pending: NextAction | None
    ) -> PendingQuestionContext | None:
        if pending is None or not pending.question_id or not pending.field:
            return None
        question = pack.questions.get(pending.question_id)
        if question is None:
            return None
        schema = pack.observation_schemas[question.observation_type]
        return PendingQuestionContext(
            question_id=question.id,
            observation_type=question.observation_type,
            field=question.collects,
            field_spec=schema.fields[question.collects],
            intent=question.intent,
        )

    async def _apply_extraction(
        self,
        pack: DomainPack,
        tenant_id: UUID,
        journey_id: UUID,
        participant_id: UUID,
        event: ParticipantEvent,
        extraction: ExtractionResult | None,
        pending: NextAction | None,
        turn_time: datetime,
    ) -> tuple[Observation | None, bool]:
        provenance_base = {
            "event_id": str(event.id),
            "extractor": f"{extraction.provider}:{extraction.model}" if extraction else None,
            "extraction_version": extraction.extraction_version if extraction else None,
            "recorded_at": turn_time.isoformat(),
        }
        if extraction and extraction.new_observations:
            created: list[Observation] = []
            for item in extraction.new_observations:
                await self._repos.observations.mark_incomplete(
                    tenant_id, journey_id, item.observation_type
                )
                created.append(
                    await self._repos.observations.add(
                        Observation(
                            tenant_id=tenant_id,
                            journey_id=journey_id,
                            participant_id=participant_id,
                            occurred_at=turn_time,
                            source="ai_extraction",
                            domain_pack=pack.id,
                            domain_pack_version=pack.version,
                            observation_type=item.observation_type,
                            observation_schema_version=item.observation_schema_version,
                            fields=item.fields,
                            confidence=item.confidence,
                            source_event_ids=[event.id],
                            extraction_version=extraction.extraction_version,
                            field_provenance={
                                name: dict(provenance_base)
                                for name, value in item.fields.items()
                                if value is not None
                            },
                        )
                    )
                )
            return created[0], True

        if pending is None or pending.observation_id is None:
            return None, False
        observation = await self._repos.observations.get(tenant_id, pending.observation_id)
        if observation is None or observation.status is not ObservationStatus.COLLECTING:
            return observation, False
        if extraction and extraction.answer:
            answer = extraction.answer
            if answer.declined:
                observation.field_provenance[answer.field] = {**provenance_base, "declined": True}
            else:
                observation.fields[answer.field] = answer.value
                observation.field_provenance[answer.field] = dict(provenance_base)
            if event.id not in observation.source_event_ids:
                observation.source_event_ids.append(event.id)
            observation.updated_at = utcnow()
            await self._repos.observations.save(observation)
        return observation, False

    @staticmethod
    def _safe_fallback_decision(blocked: PlannerDecision) -> PlannerDecision:
        log.warning("safety.decision.blocked", action=blocked.action_type)
        return blocked.model_copy(
            update={
                "action_type": NextActionType.ACKNOWLEDGE,
                "source": "safety",
                "reason": f"safety fallback: {blocked.action_type} blocked by safety policy",
                "question_id": None,
                "field": None,
                "activity_id": None,
                "guidance_ids": [],
                "response_template_id": None,
            }
        )

    @staticmethod
    def _safe_fallback_intent(pack: DomainPack, safety: SafetyPolicyValidator) -> ResponseIntent:
        log.warning("safety.intent.blocked")
        return ResponseIntent(
            kind=NextActionType.ACKNOWLEDGE,
            semantic_intent="Safe fallback acknowledgement.",
            deterministic_text=safety.safe_fallback_text,
            domain_pack=pack.id,
            domain_pack_version=pack.version,
        )


def _declined(observation: Observation) -> list[str]:
    return [f for f, p in observation.field_provenance.items() if p.get("declined")]


def _summarise_extraction(extraction: ExtractionResult | None) -> ExtractionSummary | None:
    if extraction is None:
        return None
    answer: Any = extraction.answer
    return ExtractionSummary(
        provider=extraction.provider,
        model=extraction.model,
        extraction_version=extraction.extraction_version,
        attempts=extraction.attempts,
        errors=extraction.errors,
        new_observation_types=[o.observation_type for o in extraction.new_observations],
        answered_field=answer.field if answer else None,
        declined=bool(answer and answer.declined),
    )
