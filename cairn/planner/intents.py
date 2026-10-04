"""ResponseIntent: what Cairn has decided to say, before anyone phrases it.

Cairn decides a typed ResponseIntent first; only then may an LLM phrase it. The
intent carries the semantic purpose, the approved deterministic wording, approved
guidance (which is appended verbatim and never re-phrased), tone/length limits and
prohibited topics. A renderer that cannot honour the intent falls back to the
deterministic wording.
"""

from __future__ import annotations

import string
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from cairn.domain.enums import NextActionType
from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.schemas import ResponsePolicy
from cairn.planner.planner import PlannerDecision


class GuidanceRef(BaseModel):
    id: str
    version: str
    category: str
    text: str


class ResponseIntent(BaseModel):
    kind: NextActionType
    semantic_intent: str
    # Approved wording, used verbatim by the template renderer and as LLM fallback.
    deterministic_text: str
    preamble: str | None = None
    question_id: str | None = None
    field: str | None = None
    activity_id: str | None = None
    guidance: list[GuidanceRef] = Field(default_factory=list)
    tone: str = "warm"
    max_sentences: int = 2
    prohibited_topics: list[str] = Field(default_factory=list)
    allow_llm_variation: bool = False
    template_variables: dict[str, str] = Field(default_factory=dict)
    policy_id: str | None = None
    policy_version: str | None = None
    domain_pack: str
    domain_pack_version: str


def fill_template(template: str, variables: Mapping[str, Any]) -> str | None:
    """Fill ``{field}`` placeholders; ``None`` if any placeholder is unresolved."""
    names = {f for _, f, _, _ in string.Formatter().parse(template) if f}
    values = {
        n: str(variables[n]).replace("_", " ") for n in names if variables.get(n) not in (None, "")
    }
    if names - set(values):
        return None
    return template.format(**values)


def build_response_intent(
    pack: DomainPack,
    decision: PlannerDecision,
    *,
    policy: ResponsePolicy | None,
    observation_fields: Mapping[str, Any],
    is_new_observation: bool,
    policy_just_completed: bool,
) -> ResponseIntent:
    variation = policy.llm_variation if policy else None
    prohibited = sorted(
        {
            *(policy.safety.prohibited_topics if policy else []),
            *(c.category for c in pack.safety.prohibited_claims),
        }
    )
    guidance = [
        GuidanceRef(id=g.id, version=g.version, category=g.category, text=g.text)
        for g in (pack.guidance[gid] for gid in decision.guidance_ids if gid in pack.guidance)
    ]
    common: dict[str, Any] = {
        "kind": decision.action_type,
        "guidance": guidance,
        "tone": variation.tone if variation else "warm",
        "max_sentences": variation.max_sentences if variation else 2,
        "allow_llm_variation": variation.allowed if variation else False,
        "prohibited_topics": prohibited,
        "policy_id": decision.policy_id,
        "policy_version": decision.policy_version,
        "domain_pack": pack.id,
        "domain_pack_version": pack.version,
    }

    preamble: str | None = None
    if policy and is_new_observation:
        preamble = policy.acknowledgement.on_new_observation
    elif policy and decision.action_type is NextActionType.ASK_QUESTION:
        preamble = policy.acknowledgement.on_answer

    match decision.action_type:
        case NextActionType.ASK_QUESTION:
            question = pack.questions[decision.question_id or ""]
            text = fill_template(question.template, observation_fields)
            if text is None:
                text = question.fallback_template or question.template.split("{")[0].strip()
            return ResponseIntent(
                semantic_intent=question.intent.strip(),
                deterministic_text=text,
                preamble=preamble,
                question_id=question.id,
                field=decision.field,
                template_variables={
                    k: str(v) for k, v in observation_fields.items() if v is not None
                },
                **common,
            )
        case NextActionType.REQUEST_ACTIVITY | NextActionType.REQUEST_EVIDENCE:
            activity = pack.activities[decision.activity_id or ""]
            completed_text = _template_text(
                policy, policy.completion.response_template_id if policy else None
            )
            return ResponseIntent(
                semantic_intent=activity.intent.strip(),
                deterministic_text=activity.template.strip(),
                preamble=completed_text if policy_just_completed else None,
                activity_id=activity.id,
                **common,
            )
        case NextActionType.ESCALATE:
            template = _template_text(policy, decision.response_template_id)
            return ResponseIntent(
                semantic_intent="Acknowledge and signpost to appropriate human support "
                "using only approved guidance.",
                deterministic_text=template or pack.safety.escalation_template,
                **{**common, "allow_llm_variation": False},
            )
        case NextActionType.END_SESSION | NextActionType.WAIT:
            return ResponseIntent(
                semantic_intent="Pause the conversation politely and say Cairn will "
                "check in again later.",
                deterministic_text=pack.planner.end_session_template,
                **common,
            )
        case _:
            template = _template_text(policy, decision.response_template_id)
            return ResponseIntent(
                semantic_intent="Acknowledge what the participant shared without interpreting it.",
                deterministic_text=template or pack.planner.default_acknowledgement,
                **common,
            )


def _template_text(policy: ResponsePolicy | None, template_id: str | None) -> str | None:
    if policy is None or template_id is None:
        return None
    tpl = policy.template(template_id)
    return tpl.text.strip() if tpl else None
