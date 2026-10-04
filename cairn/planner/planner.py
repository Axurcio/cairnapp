"""The deterministic Planner.

The Planner gathers candidate NextActions from every source (safety, the active
ResponsePolicy decision, pattern results, journey state), filters them against
constraints (SafetyPolicy prohibitions, burden budget, cooldowns, session question
budget) and picks the highest-priority survivor using the Domain Pack's
``action_priority``. Every candidate - selected or rejected - is returned with a
reason, so the decision is fully explainable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field

from cairn.domain.enums import JourneyStatus, NextActionType
from cairn.domain.models import PatternEvaluation, utcnow
from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.schemas import CompletionActionKind, ResponsePolicy
from cairn.policies.response_policy import AskRecord, PolicyAction, PolicyDecision

PLANNER_VERSION = "1.0.0"

_SOURCE_RANK = {"safety": 0, "journey": 1, "policy": 2, "pattern": 3, "budget": 4, "default": 5}


class SafetySignal(BaseModel):
    trigger_id: str
    guidance_id: str
    reason: str


class ActivityRecord(BaseModel):
    activity_id: str
    requested_at: datetime
    burden: int = 0


class Candidate(BaseModel):
    action_type: NextActionType
    source: str
    reason: str
    question_id: str | None = None
    field: str | None = None
    activity_id: str | None = None
    guidance_ids: list[str] = Field(default_factory=list)
    response_template_id: str | None = None
    burden: int = 0
    rejected_reason: str | None = None


class PlannerInput(BaseModel):
    journey_status: JourneyStatus
    policy: ResponsePolicy | None = None
    policy_decision: PolicyDecision | None = None
    observation_id: UUID | None = None
    safety_signal: SafetySignal | None = None
    pattern_evaluations: list[PatternEvaluation] = Field(default_factory=list)
    ask_history: list[AskRecord] = Field(default_factory=list)
    activity_history: list[ActivityRecord] = Field(default_factory=list)
    now: datetime = Field(default_factory=utcnow)


class PlannerDecision(BaseModel):
    action_type: NextActionType
    reason: str
    source: str
    question_id: str | None = None
    field: str | None = None
    activity_id: str | None = None
    guidance_ids: list[str] = Field(default_factory=list)
    response_template_id: str | None = None
    observation_id: UUID | None = None
    policy_id: str | None = None
    policy_version: str | None = None
    domain_pack: str
    domain_pack_version: str
    planner_version: str = PLANNER_VERSION
    candidates: list[Candidate] = Field(default_factory=list)


class Planner:
    def plan(self, pack: DomainPack, data: PlannerInput) -> PlannerDecision:
        candidates = self._candidates(pack, data)
        self._apply_constraints(pack, data, candidates)

        priority = {a: i for i, a in enumerate(pack.planner.action_priority)}
        viable = [c for c in candidates if c.rejected_reason is None]
        # The default candidate is a fallback: it only wins when nothing else is viable.
        viable.sort(
            key=lambda c: (
                c.source == "default",
                priority.get(c.action_type, len(priority)),
                _SOURCE_RANK.get(c.source, 99),
            )
        )
        chosen = viable[0]  # the default ACKNOWLEDGE candidate is never rejected
        for c in viable[1:]:
            c.rejected_reason = f"lower priority than {chosen.action_type} from {chosen.source}"

        guidance_ids = list(chosen.guidance_ids)
        completion = next(
            (
                c
                for c in candidates
                if c.source == "policy" and c.action_type is NextActionType.ACKNOWLEDGE
            ),
            None,
        )
        if (
            completion
            and chosen is not completion
            and chosen.action_type
            in (NextActionType.REQUEST_ACTIVITY, NextActionType.REQUEST_EVIDENCE)
        ):
            # The completed policy's approved guidance still accompanies the activity.
            guidance_ids = [*completion.guidance_ids, *guidance_ids]

        decision = data.policy_decision
        return PlannerDecision(
            action_type=chosen.action_type,
            reason=chosen.reason,
            source=chosen.source,
            question_id=chosen.question_id,
            field=chosen.field,
            activity_id=chosen.activity_id,
            guidance_ids=guidance_ids,
            response_template_id=chosen.response_template_id,
            observation_id=data.observation_id,
            policy_id=decision.policy_id if decision else None,
            policy_version=decision.policy_version if decision else None,
            domain_pack=pack.id,
            domain_pack_version=pack.version,
            candidates=candidates,
        )

    # ---------------------------------------------------------------- sources

    def _candidates(self, pack: DomainPack, data: PlannerInput) -> list[Candidate]:
        out: list[Candidate] = []

        if data.journey_status is not JourneyStatus.ACTIVE:
            out.append(
                Candidate(
                    action_type=NextActionType.WAIT,
                    source="journey",
                    reason=f"journey is {data.journey_status}",
                )
            )

        if data.safety_signal:
            out.append(
                Candidate(
                    action_type=NextActionType.ESCALATE,
                    source="safety",
                    reason=f"safety trigger '{data.safety_signal.trigger_id}': "
                    f"{data.safety_signal.reason}",
                    guidance_ids=[data.safety_signal.guidance_id],
                )
            )

        decision, policy = data.policy_decision, data.policy
        if decision and policy:
            if decision.action is PolicyAction.ASK_QUESTION and decision.question_id:
                question = pack.questions[decision.question_id]
                out.append(
                    Candidate(
                        action_type=NextActionType.ASK_QUESTION,
                        source="policy",
                        reason=decision.reason,
                        question_id=question.id,
                        field=decision.field,
                        burden=question.burden,
                    )
                )
            elif decision.action is PolicyAction.COMPLETE and decision.completion:
                completion = decision.completion
                out.append(
                    Candidate(
                        action_type=NextActionType.ACKNOWLEDGE,
                        source="policy",
                        reason=f"policy {policy.id} complete: {completion.action}",
                        guidance_ids=list(completion.guidance_ids),
                        response_template_id=completion.response_template_id,
                    )
                )
                if completion.action is CompletionActionKind.REQUEST_ACTIVITY:
                    requested = pack.activities[completion.activity_id or ""]
                    out.append(
                        Candidate(
                            action_type=NextActionType.REQUEST_ACTIVITY,
                            source="policy",
                            reason=f"policy {policy.id} completion requests activity",
                            activity_id=requested.id,
                            burden=requested.burden,
                        )
                    )
            elif decision.action is PolicyAction.BLOCKED and decision.fallback_action:
                prohibited = next(
                    r for r in policy.prohibited_when if r.id == decision.prohibited_rule_id
                )
                out.append(
                    Candidate(
                        action_type=decision.fallback_action,
                        source="policy",
                        reason=decision.reason,
                        guidance_ids=list(prohibited.guidance_ids),
                        response_template_id=prohibited.response_template_id,
                    )
                )

        for evaluation in data.pattern_evaluations:
            if not evaluation.matched:
                continue
            rule = next(r for r in pack.patterns if r.id == evaluation.rule_id)
            activity_id = rule.action.resolved_activity_id
            activity = pack.activities.get(activity_id) if activity_id else None
            out.append(
                Candidate(
                    action_type=rule.action.action_type,
                    source="pattern",
                    reason=f"pattern {rule.id}@{rule.version} matched "
                    f"({evaluation.result.get('occurrences')} occurrences in "
                    f"{rule.window_days} days)",
                    activity_id=activity_id,
                    burden=activity.burden if activity else 0,
                )
            )

        out.append(
            Candidate(
                action_type=NextActionType.ACKNOWLEDGE,
                source="default",
                reason="default acknowledgement",
            )
        )
        return out

    # ------------------------------------------------------------ constraints

    def _apply_constraints(
        self, pack: DomainPack, data: PlannerInput, candidates: list[Candidate]
    ) -> None:
        cfg = pack.planner
        prohibited = set(pack.safety.prohibited_next_actions)
        session_start = data.now - timedelta(minutes=cfg.session_window_minutes)
        day_start = data.now - timedelta(days=1)
        asked_in_session = [a for a in data.ask_history if a.asked_at >= session_start]
        burden_today = sum(
            pack.questions[a.question_id].burden
            for a in data.ask_history
            if a.asked_at >= day_start and a.question_id in pack.questions
        ) + sum(r.burden for r in data.activity_history if r.requested_at >= day_start)

        budget_exhausted = False
        for c in candidates:
            if c.source == "default":
                continue
            if c.action_type in prohibited:
                c.rejected_reason = f"{c.action_type} is prohibited by safety policy"
            elif c.action_type is NextActionType.ASK_QUESTION:
                if len(asked_in_session) >= cfg.max_questions_per_session:
                    c.rejected_reason = (
                        f"session question budget exhausted ({len(asked_in_session)}/"
                        f"{cfg.max_questions_per_session})"
                    )
                    budget_exhausted = True
                elif burden_today + c.burden > cfg.daily_burden_budget:
                    c.rejected_reason = (
                        f"daily burden budget exceeded ({burden_today}+{c.burden}>"
                        f"{cfg.daily_burden_budget})"
                    )
                    budget_exhausted = True
                elif reason := self._question_cooldown(pack, data, c):
                    c.rejected_reason = reason
            elif c.action_type in (
                NextActionType.REQUEST_ACTIVITY,
                NextActionType.REQUEST_EVIDENCE,
            ):
                if burden_today + c.burden > cfg.daily_burden_budget:
                    c.rejected_reason = "daily burden budget exceeded"
                elif reason := self._activity_cooldown(pack, data, c):
                    c.rejected_reason = reason

        if budget_exhausted and NextActionType.END_SESSION not in prohibited:
            candidates.append(
                Candidate(
                    action_type=NextActionType.END_SESSION,
                    source="budget",
                    reason="participant burden budget reached; pausing until later",
                )
            )

    @staticmethod
    def _question_cooldown(pack: DomainPack, data: PlannerInput, c: Candidate) -> str | None:
        question = pack.questions[c.question_id or ""]
        if not question.cooldown_minutes:
            return None
        since = data.now - timedelta(minutes=question.cooldown_minutes)
        recent = [
            a
            for a in data.ask_history
            if a.question_id == question.id
            and a.asked_at >= since
            and a.observation_id != data.observation_id
        ]
        return f"question {question.id} in cooldown" if recent else None

    @staticmethod
    def _activity_cooldown(pack: DomainPack, data: PlannerInput, c: Candidate) -> str | None:
        activity = pack.activities.get(c.activity_id or "")
        if activity is None or not activity.cooldown_hours:
            return None
        since = data.now - timedelta(hours=activity.cooldown_hours)
        recent = [
            r
            for r in data.activity_history
            if r.activity_id == activity.id and r.requested_at >= since
        ]
        return f"activity {activity.id} in cooldown" if recent else None
