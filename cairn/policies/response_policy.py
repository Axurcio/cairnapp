"""The deterministic ResponsePolicy engine.

Given a Domain Pack ResponsePolicy and the current state of an Observation, decide
what Cairn needs next: ask for a specific missing field, complete, or stop because
a prohibited condition holds. No LLM is involved, and every decision states the
policy id/version, the Domain Pack version and a human-readable reason.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from cairn.domain.enums import NextActionType
from cairn.domain.models import utcnow
from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.schemas import CompletionAction, RequiredField, ResponsePolicy
from cairn.policies.conditions import evaluate, is_present

ENGINE_VERSION = "1.0.0"


class PolicyAction(StrEnum):
    ASK_QUESTION = "ASK_QUESTION"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SkippedField(BaseModel):
    field: str
    question_id: str | None
    reason: str


class AskRecord(BaseModel):
    """A previously asked question (from canonical next_actions)."""

    question_id: str
    observation_id: UUID | None
    asked_at: datetime


class PolicyDecision(BaseModel):
    action: PolicyAction
    policy_id: str | None
    policy_version: str | None
    domain_pack: str
    domain_pack_version: str
    engine_version: str = ENGINE_VERSION
    reason: str
    question_id: str | None = None
    field: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    satisfied_fields: list[str] = Field(default_factory=list)
    declined_fields: list[str] = Field(default_factory=list)
    skipped_fields: list[SkippedField] = Field(default_factory=list)
    applied_branches: list[str] = Field(default_factory=list)
    completion: CompletionAction | None = None
    prohibited_rule_id: str | None = None
    fallback_action: NextActionType | None = None
    evaluated_at: datetime = Field(default_factory=utcnow)


class ResponsePolicyEngine:
    def evaluate(
        self,
        pack: DomainPack,
        policy: ResponsePolicy,
        *,
        observation_type: str,
        fields: Mapping[str, Any],
        declined_fields: Sequence[str] = (),
        observation_id: UUID | None = None,
        ask_history: Sequence[AskRecord] = (),
    ) -> PolicyDecision:
        base: dict[str, Any] = {
            "policy_id": policy.id,
            "policy_version": policy.version,
            "domain_pack": pack.id,
            "domain_pack_version": pack.version,
        }

        if policy.trigger.observation_type != observation_type:
            return PolicyDecision(
                action=PolicyAction.NOT_APPLICABLE,
                reason=f"policy triggers on '{policy.trigger.observation_type}', "
                f"not '{observation_type}'",
                **base,
            )
        if policy.trigger.conditions and not evaluate(policy.trigger.conditions, fields):
            return PolicyDecision(
                action=PolicyAction.NOT_APPLICABLE,
                reason="trigger conditions not met",
                **base,
            )

        for rule in policy.prohibited_when:
            if evaluate(rule.when, fields):
                return PolicyDecision(
                    action=PolicyAction.BLOCKED,
                    reason=f"prohibited condition '{rule.id}' holds: {rule.reason}",
                    prohibited_rule_id=rule.id,
                    fallback_action=rule.fallback_action,
                    **base,
                )

        required, applied_branches = self._effective_required(policy, fields)
        declined = set(declined_fields)
        satisfied: list[str] = []
        declined_out: list[str] = []
        skipped: list[SkippedField] = []
        missing: list[str] = []
        next_field: RequiredField | None = None
        next_question_id: str | None = None

        for rf in required:
            question = pack.question_for_field(observation_type, rf.field, rf.question_id)
            qid = question.id if question else None
            if is_present(fields.get(rf.field)):
                satisfied.append(rf.field)
                continue
            if rf.field in declined:
                declined_out.append(rf.field)
                continue
            if question and question.skip_when and evaluate(question.skip_when, fields):
                skipped.append(
                    SkippedField(
                        field=rf.field, question_id=qid, reason="question skip_when condition holds"
                    )
                )
                continue
            asks = sum(
                1
                for a in ask_history
                if a.question_id == qid
                and (observation_id is None or a.observation_id == observation_id)
            )
            if question and asks >= question.max_asks:
                skipped.append(
                    SkippedField(
                        field=rf.field, question_id=qid, reason=f"asked {asks} times (max_asks)"
                    )
                )
                continue
            missing.append(rf.field)
            if next_field is None:
                next_field, next_question_id = rf, qid

        common: dict[str, Any] = {
            "missing_fields": missing,
            "satisfied_fields": satisfied,
            "declined_fields": declined_out,
            "skipped_fields": skipped,
            "applied_branches": applied_branches,
            **base,
        }
        if next_field is not None:
            return PolicyDecision(
                action=PolicyAction.ASK_QUESTION,
                question_id=next_question_id,
                field=next_field.field,
                reason=f"required field {next_field.field} is missing",
                **common,
            )
        return PolicyDecision(
            action=PolicyAction.COMPLETE,
            completion=policy.completion,
            reason="all required fields are satisfied, declined or skipped",
            **common,
        )

    @staticmethod
    def _effective_required(
        policy: ResponsePolicy, fields: Mapping[str, Any]
    ) -> tuple[list[RequiredField], list[str]]:
        required: dict[str, RequiredField] = {rf.field: rf for rf in policy.required_fields}
        applied: list[str] = []
        for branch in policy.branches:
            if evaluate(branch.when, fields):
                applied.append(branch.id)
                for rf in branch.add_required:
                    required.setdefault(rf.field, rf)
                for name in branch.skip:
                    required.pop(name, None)

        order = {name: i for i, name in enumerate(policy.priority)}
        declared = list(required)
        ranked = sorted(
            required.values(),
            key=lambda rf: (order.get(rf.field, len(order)), declared.index(rf.field)),
        )
        return ranked, applied
