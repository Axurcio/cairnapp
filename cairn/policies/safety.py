"""Cairn-native, deterministic SafetyPolicy.

This is authoritative business logic and does not depend on NeMo Guardrails.
NeMo (or any GuardrailProvider) is defence-in-depth around LLM interaction; this
validator decides what Cairn is *allowed* to do and say:

* detect configured escalation triggers in participant input
* block NextAction types a Domain Pack prohibits
* require every piece of guidance to be approved (and human-reviewed for
  configured categories)
* reject rendered output that makes prohibited claims (diagnosis, treatment...)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.schemas import compile_patterns
from cairn.planner.intents import ResponseIntent
from cairn.planner.planner import PlannerDecision, SafetySignal


class ViolationKind(StrEnum):
    PROHIBITED_ACTION = "prohibited_action"
    UNAPPROVED_GUIDANCE = "unapproved_guidance"
    UNREVIEWED_GUIDANCE = "unreviewed_guidance"
    UNKNOWN_GUIDANCE = "unknown_guidance"
    PROHIBITED_CLAIM = "prohibited_claim"


class SafetyViolation(BaseModel):
    kind: ViolationKind
    detail: str
    rule_id: str | None = None
    category: str | None = None


class SafetyResult(BaseModel):
    allowed: bool
    violations: list[SafetyViolation] = Field(default_factory=list)
    policy_id: str
    policy_version: str


class SafetyPolicyValidator:
    def __init__(self, pack: DomainPack) -> None:
        self._pack = pack
        self._cfg = pack.safety
        self._claims = [(c, compile_patterns(c.patterns)) for c in self._cfg.prohibited_claims]
        self._triggers = [(t, compile_patterns(t.patterns)) for t in self._cfg.escalation_triggers]

    def _result(self, violations: list[SafetyViolation]) -> SafetyResult:
        return SafetyResult(
            allowed=not violations,
            violations=violations,
            policy_id=self._cfg.id,
            policy_version=self._cfg.version,
        )

    def assess_input(self, text: str) -> SafetySignal | None:
        for trigger, patterns in self._triggers:
            if any(p.search(text) for p in patterns):
                return SafetySignal(
                    trigger_id=trigger.id, guidance_id=trigger.guidance_id, reason=trigger.reason
                )
        return None

    def validate_guidance(self, guidance_ids: list[str]) -> list[SafetyViolation]:
        violations: list[SafetyViolation] = []
        for gid in guidance_ids:
            g = self._pack.guidance.get(gid)
            if g is None:
                violations.append(
                    SafetyViolation(
                        kind=ViolationKind.UNKNOWN_GUIDANCE,
                        detail=f"guidance '{gid}' is not configured",
                    )
                )
            elif not g.approved:
                violations.append(
                    SafetyViolation(
                        kind=ViolationKind.UNAPPROVED_GUIDANCE,
                        detail=f"guidance '{gid}' is not approved",
                        category=g.category,
                    )
                )
            elif g.category in self._cfg.human_review_required_categories and not g.human_reviewed:
                violations.append(
                    SafetyViolation(
                        kind=ViolationKind.UNREVIEWED_GUIDANCE,
                        detail=f"guidance '{gid}' in category '{g.category}' requires human review",
                        category=g.category,
                    )
                )
        return violations

    def validate_decision(self, decision: PlannerDecision) -> SafetyResult:
        violations: list[SafetyViolation] = []
        if decision.action_type in self._cfg.prohibited_next_actions:
            violations.append(
                SafetyViolation(
                    kind=ViolationKind.PROHIBITED_ACTION,
                    detail=f"{decision.action_type} is prohibited for {self._pack.id}",
                )
            )
        violations.extend(self.validate_guidance(decision.guidance_ids))
        return self._result(violations)

    def validate_intent(self, intent: ResponseIntent) -> SafetyResult:
        violations = self.validate_guidance([g.id for g in intent.guidance])
        for g in intent.guidance:
            configured = self._pack.guidance.get(g.id)
            if configured and configured.text.strip() != g.text.strip():
                violations.append(
                    SafetyViolation(
                        kind=ViolationKind.UNAPPROVED_GUIDANCE,
                        detail=f"guidance '{g.id}' text differs from the approved wording",
                    )
                )
        violations.extend(self.check_text(intent.deterministic_text))
        return self._result(violations)

    def check_text(self, text: str) -> list[SafetyViolation]:
        return [
            SafetyViolation(
                kind=ViolationKind.PROHIBITED_CLAIM,
                rule_id=claim.id,
                category=claim.category,
                detail=f"text matches prohibited claim '{claim.id}'",
            )
            for claim, patterns in self._claims
            if any(p.search(text) for p in patterns)
        ]

    def validate_output(self, text: str) -> SafetyResult:
        return self._result(self.check_text(text))

    @property
    def safe_fallback_text(self) -> str:
        return self._cfg.safe_fallback_text
