# ADR-007: NeMo Guardrails boundary

## Context
When an LLM is in the loop, inputs (prompt injection) and outputs (diagnosis, treatment
advice, unsupported certainty, drifting from the intent) need screening. NeMo Guardrails
is a capable option but is heavy (LangChain and friends) and must not become Cairn's
policy engine.

## Decision
Define `GuardrailProvider` (`validate_input`, `validate_context`, `validate_tool_call`,
`validate_output`) with `NoOpGuardrailProvider` (default) and `NeMoGuardrailProvider`
(optional extra: `uv sync --extra nemo`, or build with `CAIRN_EXTRAS=nemo`). The shipped
NeMo config uses deterministic custom-action rails, so it runs without an LLM. LLM
self-check rails and prompts are included and can be switched on. Any outcome other than
PASSED, including rail-modified text and errors, forces Cairn's approved template
wording. LLM tool calls are refused. NeMo is never used for authentication, tenant
isolation, consent, authorization, data residency or permissions, and Cairn's
SafetyPolicy stays authoritative.

## Consequences
- Defence-in-depth without coupling the platform to NeMo.
- The default stack stays light. Teams that enable LLM rendering should enable NeMo.
- Proposed rather than Accepted until the LLM renderer is used with real models and the
  rails are tuned against an evaluation set.

## Status
Proposed
