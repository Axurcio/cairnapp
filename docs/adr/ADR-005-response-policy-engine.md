# ADR-005: Deterministic ResponsePolicy engine

## Context
What Cairn asks next, especially in health contexts, must be predictable, testable,
reviewable by domain experts and traceable afterwards. Letting an LLM choose questions
or advice makes behaviour unauditable and unsafe.

## Decision
A deterministic engine (`cairn/policies/response_policy.py`) evaluates declarative
ResponsePolicies: trigger and conditions, required fields, priority, branches,
prohibited conditions with fallback actions, completion actions, approved templates,
safety constraints and allowed LLM variation. QuestionProtocols are separate: each
question declares the field it collects, its semantic intent, approved wording,
validation, burden, cooldown, `max_asks` and `skip_when`. The engine returns an
inspectable `PolicyDecision` (action, question, policy id and version, pack version,
reason, satisfied, declined and skipped fields). The Planner turns it into a typed
`ResponseIntent`. Only then may an LLM phrase it, within limits, with deterministic
fallback. No policy logic lives in prompts.

## Consequences
- Same inputs give the same decision, so behaviour is easy to test and explain.
- Domain experts review YAML, not prompts.
- Conversations can feel more structured than a free-form agent, which is the
  intended trade-off.

## Status
Accepted
