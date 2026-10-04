"""The loaded, cross-validated Domain Pack aggregate."""

from __future__ import annotations

import string
from dataclasses import dataclass, field

from cairn.domain_packs.schemas import (
    ActivityDefinition,
    ApprovedGuidance,
    DomainPackManifest,
    MemoryConfig,
    ObservationSchema,
    PatternRule,
    PlannerConfig,
    QuestionDefinition,
    QuestionProtocol,
    ReportTemplate,
    ResponsePolicy,
    SafetyPolicyConfig,
    compile_patterns,
)


class DomainPackError(ValueError):
    """Raised when a Domain Pack is malformed or internally inconsistent."""


@dataclass(frozen=True)
class DomainPack:
    manifest: DomainPackManifest
    observation_schemas: dict[str, ObservationSchema]
    question_protocols: list[QuestionProtocol]
    response_policies: list[ResponsePolicy]
    patterns: list[PatternRule]
    activities: dict[str, ActivityDefinition]
    safety: SafetyPolicyConfig
    guidance: dict[str, ApprovedGuidance]
    planner: PlannerConfig
    reports: dict[str, ReportTemplate]
    memory: MemoryConfig
    checksum: str
    questions: dict[str, QuestionDefinition] = field(init=False)

    def __post_init__(self) -> None:
        index: dict[str, QuestionDefinition] = {}
        for protocol in self.question_protocols:
            for q in protocol.questions:
                if q.id in index:
                    raise DomainPackError(f"duplicate question id '{q.id}'")
                index[q.id] = q
        object.__setattr__(self, "questions", index)

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    def policy_for(self, observation_type: str) -> ResponsePolicy | None:
        return next(
            (p for p in self.response_policies if p.trigger.observation_type == observation_type),
            None,
        )

    def question_for_field(
        self, observation_type: str, field_name: str, explicit_id: str | None = None
    ) -> QuestionDefinition | None:
        if explicit_id:
            return self.questions.get(explicit_id)
        candidates = [
            q
            for q in self.questions.values()
            if q.observation_type == observation_type and q.collects == field_name
        ]
        return min(candidates, key=lambda q: q.priority) if candidates else None

    def patterns_for(self, observation_type: str) -> list[PatternRule]:
        return [p for p in self.patterns if p.observation_type == observation_type]

    # ------------------------------------------------------------ validation

    def validate_references(self) -> list[str]:
        """Return a list of cross-reference problems (empty when the pack is consistent)."""
        problems: list[str] = []
        schemas = self.observation_schemas

        def check_fields(where: str, obs_type: str, names: set[str]) -> None:
            schema = schemas.get(obs_type)
            if schema is None:
                problems.append(f"{where}: unknown observation_type '{obs_type}'")
                return
            unknown = names - set(schema.fields)
            if unknown:
                problems.append(f"{where}: unknown fields {sorted(unknown)} for '{obs_type}'")

        def check_guidance(where: str, ids: list[str]) -> None:
            for gid in ids:
                g = self.guidance.get(gid)
                if g is None:
                    problems.append(f"{where}: unknown guidance '{gid}'")
                elif not g.approved:
                    problems.append(f"{where}: guidance '{gid}' is not approved")

        for schema in schemas.values():
            if schema.mock_extraction:
                hints = schema.mock_extraction
                try:
                    compile_patterns(hints.trigger_patterns)
                    for pats in hints.field_patterns.values():
                        compile_patterns([p.pattern for p in pats])
                except Exception as exc:  # re.error
                    problems.append(f"observation {schema.observation_type}: bad regex: {exc}")
                check_fields(
                    f"observation {schema.observation_type} mock_extraction",
                    schema.observation_type,
                    set(hints.field_patterns) | set(hints.defaults),
                )

        for q in self.questions.values():
            check_fields(f"question {q.id}", q.observation_type, {q.collects})
            if q.skip_when:
                check_fields(
                    f"question {q.id} skip_when",
                    q.observation_type,
                    q.skip_when.referenced_fields(),
                )
            check_fields(f"question {q.id} template", q.observation_type, q.template_placeholders())

        seen_policy_types: set[str] = set()
        for p in self.response_policies:
            where = f"response_policy {p.id}@{p.version}"
            obs_type = p.trigger.observation_type
            if obs_type in seen_policy_types:
                problems.append(f"{where}: more than one policy triggers on '{obs_type}'")
            seen_policy_types.add(obs_type)
            required = {r.field for r in p.required_fields}
            branch_fields = {r.field for b in p.branches for r in b.add_required}
            check_fields(where, obs_type, required | branch_fields)
            if p.trigger.conditions:
                check_fields(where, obs_type, p.trigger.conditions.referenced_fields())
            unknown_priority = set(p.priority) - required - branch_fields
            if unknown_priority:
                problems.append(f"{where}: priority lists non-required {sorted(unknown_priority)}")
            for rf in [*p.required_fields, *(r for b in p.branches for r in b.add_required)]:
                if self.question_for_field(obs_type, rf.field, rf.question_id) is None:
                    problems.append(f"{where}: no question collects '{rf.field}'")
            for b in p.branches:
                check_fields(f"{where} branch {b.id}", obs_type, b.when.referenced_fields())
            for prohibited in p.prohibited_when:
                check_fields(
                    f"{where} prohibited {prohibited.id}",
                    obs_type,
                    prohibited.when.referenced_fields(),
                )
                if p.template(prohibited.response_template_id) is None:
                    problems.append(
                        f"{where}: unknown template '{prohibited.response_template_id}'"
                    )
                check_guidance(f"{where} prohibited {prohibited.id}", prohibited.guidance_ids)
            if p.template(p.completion.response_template_id) is None:
                problems.append(
                    f"{where}: unknown completion template '{p.completion.response_template_id}'"
                )
            check_guidance(f"{where} completion", p.completion.guidance_ids)
            if p.completion.activity_id and p.completion.activity_id not in self.activities:
                problems.append(f"{where}: unknown activity '{p.completion.activity_id}'")

        for rule in self.patterns:
            where = f"pattern {rule.id}@{rule.version}"
            check_fields(
                where,
                rule.observation_type,
                rule.where.referenced_fields() if rule.where else set(),
            )
            activity = rule.action.resolved_activity_id
            if activity and activity not in self.activities:
                problems.append(f"{where}: unknown activity '{activity}'")

        for trig in self.safety.escalation_triggers:
            check_guidance(f"safety escalation {trig.id}", [trig.guidance_id])
        try:
            for claim in self.safety.prohibited_claims:
                compile_patterns(claim.patterns)
            for trig in self.safety.escalation_triggers:
                compile_patterns(trig.patterns)
        except Exception as exc:  # re.error
            problems.append(f"safety: bad regex: {exc}")

        for tpl in self.reports.values():
            for section in tpl.sections:
                check_fields(
                    f"report {tpl.id} section '{section.title}'",
                    section.observation_type,
                    set(section.fields),
                )
        default_report = self.manifest.default_report_template
        if default_report and default_report not in self.reports:
            problems.append(f"manifest: unknown default_report_template '{default_report}'")

        for text in (self.planner.default_acknowledgement, self.planner.end_session_template):
            if any(f for _, f, _, _ in string.Formatter().parse(text) if f):
                problems.append("planner templates must not contain placeholders")
        return problems
