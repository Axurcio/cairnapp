"""Planner candidate selection and the deterministic PatternEngine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cairn.domain.enums import JourneyStatus, NextActionType
from cairn.domain.models import Observation
from cairn.domain_packs.pack import DomainPack
from cairn.patterns.engine import PatternEngine
from cairn.planner.planner import Planner, PlannerInput, SafetySignal
from cairn.policies.response_policy import AskRecord, ResponsePolicyEngine

T, J, P = uuid4(), uuid4(), uuid4()
NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)


def _obs(pack: DomainPack, days_ago: int, **fields: object) -> Observation:
    return Observation(
        tenant_id=T,
        journey_id=J,
        participant_id=P,
        observation_type="career_challenge",
        observation_schema_version="1.0.0",
        fields=dict(fields),
        extraction_version="1",
        occurred_at=NOW - timedelta(days=days_ago),
        source_event_ids=[uuid4()],
        domain_pack=pack.id,
        domain_pack_version=pack.version,
    )


def test_pattern_matches_with_evidence_refs(mentorship: DomainPack) -> None:
    observations = [_obs(mentorship, d, issue="project_opportunity") for d in (50, 20, 0)]
    observations.append(_obs(mentorship, 1, issue="feedback"))  # filtered by `where`
    observations.append(_obs(mentorship, 90, issue="project_opportunity"))  # outside window
    [evaluation] = PatternEngine().evaluate(
        mentorship,
        "career_challenge",
        observations,
        tenant_id=T,
        journey_id=J,
        participant_id=P,
        now=NOW,
    )
    assert evaluation.matched
    assert evaluation.rule_id == "repeated_project_opportunity_blocker"
    assert evaluation.rule_version == "1.0.0"
    assert evaluation.algorithm == "occurrence_count"
    assert evaluation.algorithm_version == "1.0.0"
    assert evaluation.result["occurrences"] == 3
    assert set(evaluation.evidence_refs) == {o.id for o in observations[:3]}
    assert len(evaluation.source_event_ids) == 3
    assert evaluation.suggested_action == "explore_blocker"


def test_pattern_not_matched_below_threshold(mentorship: DomainPack) -> None:
    observations = [_obs(mentorship, d, issue="project_opportunity") for d in (5, 0)]
    [evaluation] = PatternEngine().evaluate(
        mentorship,
        "career_challenge",
        observations,
        tenant_id=T,
        journey_id=J,
        participant_id=P,
        now=NOW,
    )
    assert not evaluation.matched
    assert evaluation.suggested_action is None


def _policy_input(pack: DomainPack, **kwargs: object) -> PlannerInput:
    policy = pack.policy_for("career_challenge")
    assert policy is not None
    decision = ResponsePolicyEngine().evaluate(
        pack,
        policy,
        observation_type="career_challenge",
        fields={"issue": "project_opportunity", "recent_example": None},
    )
    return PlannerInput(
        journey_status=JourneyStatus.ACTIVE,
        policy=policy,
        policy_decision=decision,
        now=NOW,
        **kwargs,
    )  # type: ignore[arg-type]


def test_question_outranks_pattern_activity_and_both_are_explained(mentorship: DomainPack) -> None:
    observations = [_obs(mentorship, d, issue="project_opportunity") for d in (40, 20, 0)]
    evaluations = PatternEngine().evaluate(
        mentorship,
        "career_challenge",
        observations,
        tenant_id=T,
        journey_id=J,
        participant_id=P,
        now=NOW,
    )
    decision = Planner().plan(
        mentorship, _policy_input(mentorship, pattern_evaluations=evaluations)
    )
    assert decision.action_type is NextActionType.ASK_QUESTION
    assert decision.question_id == "recent_project_example"
    activity = next(c for c in decision.candidates if c.source == "pattern")
    assert activity.activity_id == "explore_blocker"
    assert activity.rejected_reason is not None
    assert "lower priority" in activity.rejected_reason


def test_safety_signal_escalates(mentorship: DomainPack) -> None:
    signal = SafetySignal(trigger_id="crisis", guidance_id="crisis_support", reason="test")
    decision = Planner().plan(mentorship, _policy_input(mentorship, safety_signal=signal))
    assert decision.action_type is NextActionType.ESCALATE
    assert decision.guidance_ids == ["crisis_support"]


def test_session_budget_exhaustion_ends_session(mentorship: DomainPack) -> None:
    history = [
        AskRecord(
            question_id="career.desired_outcome",
            observation_id=uuid4(),
            asked_at=NOW - timedelta(minutes=5),
        )
        for _ in range(6)
    ]
    decision = Planner().plan(mentorship, _policy_input(mentorship, ask_history=history))
    assert decision.action_type is NextActionType.END_SESSION
    ask = next(c for c in decision.candidates if c.action_type is NextActionType.ASK_QUESTION)
    assert ask.rejected_reason is not None
    assert "session question budget" in ask.rejected_reason


def test_default_acknowledgement_without_policy(demo: DomainPack) -> None:
    decision = Planner().plan(demo, PlannerInput(journey_status=JourneyStatus.ACTIVE, now=NOW))
    assert decision.action_type is NextActionType.ACKNOWLEDGE
    assert decision.source == "default"
