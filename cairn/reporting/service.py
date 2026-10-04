"""Descriptive reports built deterministically from canonical observations.

Reports only restate what the participant reported, in the Domain Pack's
configured structure, and every statement links to its source events. No LLM,
no interpretation, no diagnosis.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from cairn.domain.models import Journey, Observation, Report, ReportSection, ReportStatement
from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.schemas import FieldType, ObservationSchema

_DURATION_PART = re.compile(r"(\d+)([YMWD])")
_DURATION_UNITS = {"Y": "year", "M": "month", "W": "week", "D": "day"}


class NoReportTemplate(LookupError):
    pass


def humanize(schema: ObservationSchema, field_name: str, value: Any) -> str:
    spec = schema.fields[field_name]
    if spec.type is FieldType.DURATION and isinstance(value, str):
        parts = [
            f"{n} {_DURATION_UNITS[u]}{'s' if n != '1' else ''}"
            for n, u in _DURATION_PART.findall(value)
        ]
        return ", ".join(parts) or value
    if spec.type is FieldType.ENUM and isinstance(value, str):
        return value.replace("_", " ")
    return str(value)


def build_report(
    pack: DomainPack,
    journey: Journey,
    observations: Sequence[Observation],
    template_id: str | None = None,
) -> Report:
    template_id = template_id or pack.manifest.default_report_template
    if not template_id or template_id not in pack.reports:
        raise NoReportTemplate(template_id or "<none>")
    template = pack.reports[template_id]
    sections: list[ReportSection] = []
    for section in template.sections:
        schema = pack.observation_schemas[section.observation_type]
        statements: list[ReportStatement] = []
        for obs in observations:
            if obs.observation_type != section.observation_type:
                continue
            parts = [
                f"{schema.fields[f].label or f.replace('_', ' ')}: "
                f"{humanize(schema, f, obs.fields[f])}"
                for f in section.fields
                if obs.fields.get(f) is not None
            ]
            if not parts:
                continue
            statements.append(
                ReportStatement(
                    text=f"{obs.occurred_at.date().isoformat()} ({obs.status}) - "
                    + "; ".join(parts),
                    observation_id=obs.id,
                    source_event_ids=list(obs.source_event_ids),
                    source_evidence_ids=list(obs.source_evidence_ids),
                )
            )
        if not statements:
            statements.append(ReportStatement(text=section.empty_text))
        sections.append(ReportSection(title=section.title, statements=statements))
    return Report(
        tenant_id=journey.tenant_id,
        journey_id=journey.id,
        template_id=template.id,
        template_version=template.version,
        domain_pack=pack.id,
        domain_pack_version=pack.version,
        disclaimer=template.disclaimer.strip(),
        sections=sections,
    )
