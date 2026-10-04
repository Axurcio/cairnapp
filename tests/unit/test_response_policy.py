"""ResponsePolicy engine: deterministic, versioned, inspectable decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from cairn.domain.enums import NextActionType
from cairn.domain_packs.pack import DomainPack
from cairn.policies.response_policy import AskRecord, PolicyAction, ResponsePolicyEngine

HAND_SHAKING = {
    "type": "hand_shaking",
    "body_location": "hand",
    "side": "right",
    "duration": None,
    "severity": None,
    "frequency": None,
    "activity_context": None,
    "functional_impact": None,
}


def _fields(**overrides: object) -> dict[str, object]:
    fields = {k: v for k, v in HAND_SHAKING.items() if k != "type"}
    fields.update(overrides)
    return fields


def test_a_hand_shaking_missing_duration_asks_duration(parkinsons: DomainPack) -> None:
    policy = parkinsons.policy_for("hand_shaking")
    assert policy is not None
    decision = ResponsePolicyEngine().evaluate(
        parkinsons, policy, observation_type="hand_shaking", fields=_fields()
    )
    assert decision.action is PolicyAction.ASK_QUESTION
    assert decision.question_id == "hand_shaking.duration"
    assert decision.field == "duration"
    assert decision.policy_id == "hand_shaking_followup"
    assert decision.policy_version == "1.0.0"
    assert decision.domain_pack == "parkinsons"
    assert decision.domain_pack_version == parkinsons.version
    assert decision.reason == "required field duration is missing"


def test_b_progression_selects_next_configured_field(parkinsons: DomainPack) -> None:
    policy = parkinsons.policy_for("hand_shaking")
    assert policy is not None
    engine = ResponsePolicyEngine()

    after_duration = engine.evaluate(
        parkinsons, policy, observation_type="hand_shaking", fields=_fields(duration="P3M")
    )
    assert after_duration.question_id == "hand_shaking.severity"
    assert after_duration.satisfied_fields == ["duration"]

    after_severity = engine.evaluate(
        parkinsons,
        policy,
        observation_type="hand_shaking",
        fields=_fields(duration="P3M", severity=4),
    )
    assert after_severity.question_id == "hand_shaking.frequency"

    complete = engine.evaluate(
        parkinsons,
        policy,
        observation_type="hand_shaking",
        fields=_fields(
            duration="P3M",
            severity=4,
            frequency="daily",
            activity_context="holding a cup",
            functional_impact="writing is slower",
        ),
    )
    assert complete.action is PolicyAction.COMPLETE
    assert complete.completion is not None
    assert complete.completion.action == "acknowledge_and_record"
    assert complete.completion.guidance_ids == ["note_when_shaking_occurs"]


def test_c_mentorship_missing_recent_example_asks_for_it(mentorship: DomainPack) -> None:
    policy = mentorship.policy_for("career_challenge")
    assert policy is not None
    decision = ResponsePolicyEngine().evaluate(
        mentorship,
        policy,
        observation_type="career_challenge",
        fields={
            "topic": "leadership",
            "issue": "project_opportunity",
            "goal": "greater_responsibility",
            "recent_example": None,
        },
    )
    assert decision.action is PolicyAction.ASK_QUESTION
    assert decision.question_id == "recent_project_example"
    assert decision.policy_id == "career_challenge_followup"


def test_branch_adds_required_field_in_priority_order(parkinsons: DomainPack) -> None:
    policy = parkinsons.policy_for("hand_shaking")
    assert policy is not None
    decision = ResponsePolicyEngine().evaluate(
        parkinsons,
        policy,
        observation_type="hand_shaking",
        fields=_fields(side="both", duration="P2W"),
    )
    assert decision.applied_branches == ["both_sides"]
    assert decision.question_id == "hand_shaking.onset_side"


def test_skip_when_condition_skips_question(parkinsons: DomainPack) -> None:
    policy = parkinsons.policy_for("hand_shaking")
    assert policy is not None
    decision = ResponsePolicyEngine().evaluate(
        parkinsons,
        policy,
        observation_type="hand_shaking",
        fields=_fields(
            duration="P1M", severity=0, frequency="occasionally", activity_context="typing"
        ),
    )
    assert decision.action is PolicyAction.COMPLETE
    assert [s.field for s in decision.skipped_fields] == ["functional_impact"]


def test_declined_field_is_not_asked_again(parkinsons: DomainPack) -> None:
    policy = parkinsons.policy_for("hand_shaking")
    assert policy is not None
    decision = ResponsePolicyEngine().evaluate(
        parkinsons,
        policy,
        observation_type="hand_shaking",
        fields=_fields(duration="P3M"),
        declined_fields=["severity"],
    )
    assert decision.question_id == "hand_shaking.frequency"
    assert decision.declined_fields == ["severity"]


def test_max_asks_prevents_infinite_reasking(parkinsons: DomainPack) -> None:
    policy = parkinsons.policy_for("hand_shaking")
    assert policy is not None
    obs_id = uuid4()
    now = datetime.now(UTC)
    history = [
        AskRecord(question_id="hand_shaking.duration", observation_id=obs_id, asked_at=now)
        for _ in range(2)
    ]
    decision = ResponsePolicyEngine().evaluate(
        parkinsons,
        policy,
        observation_type="hand_shaking",
        fields=_fields(),
        observation_id=obs_id,
        ask_history=history,
    )
    assert decision.question_id == "hand_shaking.severity"
    assert decision.skipped_fields[0].reason.startswith("asked 2 times")


def test_prohibited_condition_blocks_with_fallback(mentorship: DomainPack) -> None:
    policy = mentorship.policy_for("career_challenge")
    assert policy is not None
    decision = ResponsePolicyEngine().evaluate(
        mentorship,
        policy,
        observation_type="career_challenge",
        fields={"issue": "harassment_or_discrimination"},
    )
    assert decision.action is PolicyAction.BLOCKED
    assert decision.prohibited_rule_id == "harassment_or_discrimination"
    assert decision.fallback_action is NextActionType.ESCALATE


def test_policy_not_applicable_to_other_observation_types(demo: DomainPack) -> None:
    policy = demo.policy_for("reading_session")
    assert policy is not None
    decision = ResponsePolicyEngine().evaluate(
        demo, policy, observation_type="hand_shaking", fields={}
    )
    assert decision.action is PolicyAction.NOT_APPLICABLE


def test_decisions_are_deterministic(parkinsons: DomainPack) -> None:
    policy = parkinsons.policy_for("hand_shaking")
    assert policy is not None
    engine = ResponsePolicyEngine()
    runs = {
        engine.evaluate(
            parkinsons, policy, observation_type="hand_shaking", fields=_fields(duration="P3M")
        ).model_dump_json(exclude={"evaluated_at"})
        for _ in range(20)
    }
    assert len(runs) == 1
