"""Formal schemas for Domain Pack content.

A Domain Pack is configuration + schemas + rules. It can never contain code that
bypasses platform controls: everything here is data, validated by Pydantic and
executed by Cairn's deterministic engines (ResponsePolicy, Planner, PatternEngine,
SafetyPolicy). Every artefact carries a semantic version so that any decision can
be traced to the exact rule version that produced it.
"""

from __future__ import annotations

import re
import string
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from cairn.domain.enums import EventType, NextActionType

SemVer = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
QuestionId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]*$")]


class PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ============================================================== conditions


class ConditionOp(StrEnum):
    EXISTS = "exists"
    MISSING = "missing"
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"


class Condition(PackModel):
    """A declarative predicate over observation fields.

    Either a leaf (``field`` + ``op`` [+ ``value``]) or a composite
    (``all`` / ``any`` / ``not``). Evaluated by :mod:`cairn.policies.conditions`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    field: str | None = None
    op: ConditionOp | None = None
    value: Any = None
    all: list[Condition] | None = None
    any: list[Condition] | None = None
    not_: Condition | None = Field(default=None, alias="not")

    @model_validator(mode="after")
    def _exactly_one_form(self) -> Condition:
        forms = [
            self.field is not None,
            self.all is not None,
            self.any is not None,
            self.not_ is not None,
        ]
        if sum(forms) != 1:
            raise ValueError("condition must be exactly one of: field/op, all, any, not")
        if self.field is not None and self.op is None:
            raise ValueError("leaf condition requires 'op'")
        return self

    def referenced_fields(self) -> set[str]:
        if self.field is not None:
            return {self.field}
        out: set[str] = set()
        for child in [*(self.all or []), *(self.any or [])]:
            out |= child.referenced_fields()
        if self.not_ is not None:
            out |= self.not_.referenced_fields()
        return out


# ============================================================== observations


class FieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    # ISO-8601 duration, e.g. P3M (three months), P2W, P10D.
    DURATION = "duration"
    DATE = "date"


class FieldSpec(PackModel):
    type: FieldType
    description: str = ""
    values: list[str] | None = None
    # Synonyms help the deterministic mock parser map free text onto enum values.
    synonyms: dict[str, list[str]] = Field(default_factory=dict)
    minimum: float | None = None
    maximum: float | None = None
    max_length: int = 1000
    label: str | None = None

    @model_validator(mode="after")
    def _enum_has_values(self) -> FieldSpec:
        if self.type is FieldType.ENUM and not self.values:
            raise ValueError("enum fields require 'values'")
        if self.type is not FieldType.ENUM and self.values:
            raise ValueError("'values' is only valid for enum fields")
        unknown = set(self.synonyms) - set(self.values or [])
        if unknown:
            raise ValueError(f"synonyms reference unknown enum values: {sorted(unknown)}")
        return self


class MockFieldPattern(PackModel):
    pattern: str
    value: Any


class MockExtractionHints(PackModel):
    """Deterministic hints used ONLY by MockAIProvider for dev/test.

    Real providers never see these; they are not business rules.
    """

    trigger_patterns: list[str]
    field_patterns: dict[str, list[MockFieldPattern]] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)


class ObservationSchema(PackModel):
    observation_type: Slug
    version: SemVer
    description: str
    fields: dict[str, FieldSpec]
    mock_extraction: MockExtractionHints | None = None


# ============================================================== questions


class QuestionValidation(PackModel):
    type: FieldType


class QuestionDefinition(PackModel):
    id: QuestionId
    observation_type: Slug
    collects: str
    # The semantic purpose. An LLM may re-phrase, never re-purpose.
    intent: str
    # Approved deterministic wording; {field} placeholders resolve from the observation.
    template: str
    fallback_template: str | None = None
    validation: QuestionValidation | None = None
    priority: int = 100
    burden: int = Field(default=1, ge=0)
    cooldown_minutes: int = Field(default=0, ge=0)
    max_asks: int = Field(default=2, ge=1)
    # When not to ask: if this condition holds, the field is skipped.
    skip_when: Condition | None = None

    def template_placeholders(self) -> set[str]:
        names: set[str] = set()
        for tpl in (self.template, self.fallback_template or ""):
            names |= {f for _, f, _, _ in string.Formatter().parse(tpl) if f}
        return names


class QuestionProtocol(PackModel):
    id: Slug
    version: SemVer
    description: str = ""
    questions: list[QuestionDefinition]


# ============================================================== response policy


class Trigger(PackModel):
    observation_type: Slug
    conditions: Condition | None = None


class RequiredField(PackModel):
    field: str
    question_id: QuestionId | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, data: Any) -> Any:
        return {"field": data} if isinstance(data, str) else data


class PolicyBranch(PackModel):
    id: Slug
    when: Condition
    add_required: list[RequiredField] = Field(default_factory=list)
    skip: list[str] = Field(default_factory=list)


class ProhibitedRule(PackModel):
    """If ``when`` holds, the policy must not continue; Cairn takes ``fallback_action``."""

    id: Slug
    when: Condition
    fallback_action: NextActionType
    reason: str
    response_template_id: str
    guidance_ids: list[str] = Field(default_factory=list)


class CompletionActionKind(StrEnum):
    ACKNOWLEDGE_AND_RECORD = "acknowledge_and_record"
    REQUEST_ACTIVITY = "request_activity"


class CompletionAction(PackModel):
    action: CompletionActionKind
    response_template_id: str
    guidance_ids: list[str] = Field(default_factory=list)
    activity_id: str | None = None

    @model_validator(mode="after")
    def _activity_needed(self) -> CompletionAction:
        if self.action is CompletionActionKind.REQUEST_ACTIVITY and not self.activity_id:
            raise ValueError("request_activity completion requires activity_id")
        return self


class ResponseTemplate(PackModel):
    id: str
    intent: str
    text: str


class Acknowledgement(PackModel):
    on_new_observation: str | None = None
    on_answer: str | None = None


class LLMVariation(PackModel):
    allowed: bool = True
    tone: str = "warm"
    max_sentences: int = Field(default=2, ge=1, le=6)


class SafetyConstraint(PackModel):
    prohibited_topics: list[str] = Field(default_factory=list)
    requires_approved_guidance: bool = True


class ResponsePolicy(PackModel):
    id: Slug
    version: SemVer
    description: str = ""
    trigger: Trigger
    required_fields: list[RequiredField]
    priority: list[str] = Field(default_factory=list)
    branches: list[PolicyBranch] = Field(default_factory=list)
    prohibited_when: list[ProhibitedRule] = Field(default_factory=list)
    acknowledgement: Acknowledgement = Field(default_factory=Acknowledgement)
    completion: CompletionAction
    templates: list[ResponseTemplate] = Field(default_factory=list)
    safety: SafetyConstraint = Field(default_factory=SafetyConstraint)
    llm_variation: LLMVariation = Field(default_factory=LLMVariation)

    def template(self, template_id: str) -> ResponseTemplate | None:
        return next((t for t in self.templates if t.id == template_id), None)


# ============================================================== patterns


class PatternAction(PackModel):
    suggest_next_action: str
    action_type: NextActionType = NextActionType.REQUEST_ACTIVITY
    activity_id: str | None = None

    @property
    def resolved_activity_id(self) -> str | None:
        if self.action_type in (NextActionType.REQUEST_ACTIVITY, NextActionType.REQUEST_EVIDENCE):
            return self.activity_id or self.suggest_next_action
        return self.activity_id


class PatternRule(PackModel):
    id: Slug
    version: SemVer
    description: str = ""
    algorithm: str = "occurrence_count"
    observation_type: Slug
    where: Condition | None = None
    window_days: int = Field(ge=1)
    minimum_occurrences: int = Field(ge=1)
    action: PatternAction


# ============================================================== activities


class ActivityDefinition(PackModel):
    id: Slug
    version: SemVer
    title: str
    intent: str
    template: str
    burden: int = Field(default=2, ge=0)
    cooldown_hours: int = Field(default=24, ge=0)
    evidence_capture_types: list[str] = Field(default_factory=list)


# ============================================================== safety


class ProhibitedClaim(PackModel):
    id: Slug
    category: str
    patterns: list[str]


class EscalationTrigger(PackModel):
    id: Slug
    patterns: list[str]
    guidance_id: str
    reason: str


class SafetyPolicyConfig(PackModel):
    id: Slug
    version: SemVer
    # Health packs must remain descriptive unless an approved regulatory profile says otherwise.
    descriptive_only: bool = True
    prohibited_next_actions: list[NextActionType] = Field(default_factory=list)
    prohibited_claims: list[ProhibitedClaim] = Field(default_factory=list)
    escalation_triggers: list[EscalationTrigger] = Field(default_factory=list)
    escalation_template: str = "Thank you for telling me."
    human_review_required_categories: list[str] = Field(default_factory=list)
    safe_fallback_text: str


class ApprovedGuidance(PackModel):
    id: Slug
    version: SemVer
    category: str
    text: str
    approved: bool
    human_reviewed: bool = False
    reviewed_by: str | None = None
    notes: str | None = None


# ============================================================== planner


class PlannerConfig(PackModel):
    version: SemVer
    # Highest priority first. Candidates of unlisted types rank last.
    action_priority: list[NextActionType]
    max_questions_per_session: int = Field(default=8, ge=1)
    session_window_minutes: int = Field(default=180, ge=1)
    daily_burden_budget: int = Field(default=20, ge=1)
    default_acknowledgement: str
    end_session_template: str
    follow_up_after_hours: float = Field(default=72.0, gt=0)


# ============================================================== reports


class ReportSectionTemplate(PackModel):
    title: str
    observation_type: Slug
    fields: list[str]
    empty_text: str = "No observations recorded."


class ReportTemplate(PackModel):
    id: Slug
    version: SemVer
    title: str
    disclaimer: str
    sections: list[ReportSectionTemplate]


# ============================================================== memory


class MemoryConfig(PackModel):
    """How this pack's canonical events are projected into derived context memory."""

    version: SemVer
    project_event_types: list[EventType] = Field(
        default_factory=lambda: [EventType.PARTICIPANT_MESSAGE]
    )
    project_observation_summaries: bool = True
    recall_limit: int = Field(default=5, ge=0, le=50)
    # Hints for full Graphiti entity extraction (ignored in episodes mode).
    entity_hints: dict[str, str] = Field(default_factory=dict)


# ============================================================== manifest


class IntegrationAdapterRef(PackModel):
    """Declares an optional external integration. Adapters are platform code, never pack code."""

    id: Slug
    kind: str
    description: str = ""
    enabled: bool = False


class DomainPackManifest(PackModel):
    schema_version: Literal["1"]
    id: Slug
    name: str
    version: SemVer
    description: str
    classification: Literal["non_clinical", "health", "wellbeing"]
    regulatory_profile: str = "descriptive_only"
    synthetic_sample: bool = False
    terminology: dict[str, str] = Field(default_factory=dict)
    default_report_template: str | None = None
    integrations: list[IntegrationAdapterRef] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)

    @property
    def major_version(self) -> int:
        return int(self.version.split(".")[0])


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]
