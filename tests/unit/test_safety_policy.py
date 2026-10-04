"""Cairn-native SafetyPolicy (authoritative; independent of NeMo)."""

from __future__ import annotations

from cairn.domain.enums import NextActionType
from cairn.domain_packs.pack import DomainPack
from cairn.planner.intents import GuidanceRef, ResponseIntent
from cairn.planner.planner import PlannerDecision
from cairn.policies.safety import SafetyPolicyValidator, ViolationKind


def _decision(pack: DomainPack, action: NextActionType, guidance: list[str]) -> PlannerDecision:
    return PlannerDecision(
        action_type=action,
        reason="test",
        source="policy",
        guidance_ids=guidance,
        domain_pack=pack.id,
        domain_pack_version=pack.version,
    )


def test_e_unapproved_treatment_recommendation_is_rejected(parkinsons: DomainPack) -> None:
    validator = SafetyPolicyValidator(parkinsons)
    result = validator.validate_output("You should increase your medication to 50 mg.")
    assert not result.allowed
    assert {v.category for v in result.violations} == {"treatment_recommendation"}
    assert result.policy_id == "parkinsons_sample_safety"


def test_e_guidance_not_in_approved_catalogue_is_rejected(parkinsons: DomainPack) -> None:
    validator = SafetyPolicyValidator(parkinsons)
    result = validator.validate_decision(
        _decision(parkinsons, NextActionType.ACKNOWLEDGE, ["drink_chamomile_tea"])
    )
    assert not result.allowed
    assert result.violations[0].kind is ViolationKind.UNKNOWN_GUIDANCE


def test_e_tampered_guidance_text_is_rejected(parkinsons: DomainPack) -> None:
    validator = SafetyPolicyValidator(parkinsons)
    intent = ResponseIntent(
        kind=NextActionType.ACKNOWLEDGE,
        semantic_intent="ack",
        deterministic_text="Noted.",
        guidance=[
            GuidanceRef(
                id="note_when_shaking_occurs",
                version="1.0.0",
                category="evidence_gathering",
                text="You should start taking a new medication.",
            )
        ],
        domain_pack=parkinsons.id,
        domain_pack_version=parkinsons.version,
    )
    result = validator.validate_intent(intent)
    assert not result.allowed
    assert any(v.kind is ViolationKind.UNAPPROVED_GUIDANCE for v in result.violations)


def test_diagnosis_claims_are_rejected(parkinsons: DomainPack) -> None:
    validator = SafetyPolicyValidator(parkinsons)
    for text in (
        "You have Parkinson's.",
        "This is Parkinsonian tremor.",
        "This confirms Parkinson's.",
    ):
        assert not validator.validate_output(text).allowed, text


def test_approved_evidence_gathering_guidance_passes(parkinsons: DomainPack) -> None:
    validator = SafetyPolicyValidator(parkinsons)
    assert validator.validate_decision(
        _decision(parkinsons, NextActionType.ACKNOWLEDGE, ["note_when_shaking_occurs"])
    ).allowed
    assert validator.validate_output(
        "Thanks for telling me. How long have you noticed the shaking in your right hand?"
    ).allowed


def test_human_review_required_category(parkinsons: DomainPack, demo: DomainPack) -> None:
    clinical = SafetyPolicyValidator(parkinsons).validate_decision(
        _decision(parkinsons, NextActionType.ACKNOWLEDGE, ["example_unreviewed_clinical_tip"])
    )
    assert clinical.violations[0].kind is ViolationKind.UNREVIEWED_GUIDANCE
    expert = SafetyPolicyValidator(demo).validate_decision(
        _decision(demo, NextActionType.ACKNOWLEDGE, ["unreviewed_expert_tip"])
    )
    assert expert.violations[0].kind is ViolationKind.UNREVIEWED_GUIDANCE


def test_unapproved_guidance_rejected(demo: DomainPack) -> None:
    result = SafetyPolicyValidator(demo).validate_decision(
        _decision(demo, NextActionType.ACKNOWLEDGE, ["draft_tip"])
    )
    assert result.violations[0].kind is ViolationKind.UNAPPROVED_GUIDANCE


def test_prohibited_next_action_blocked(demo: DomainPack) -> None:
    result = SafetyPolicyValidator(demo).validate_decision(
        _decision(demo, NextActionType.REQUEST_EVIDENCE, [])
    )
    assert result.violations[0].kind is ViolationKind.PROHIBITED_ACTION


def test_escalation_trigger_detected_in_input(parkinsons: DomainPack) -> None:
    signal = SafetyPolicyValidator(parkinsons).assess_input("I fell over this morning")
    assert signal is not None
    assert signal.trigger_id == "fall_or_injury"
    assert signal.guidance_id == "contact_care_team"
    assert SafetyPolicyValidator(parkinsons).assess_input("My hand shakes a bit") is None
