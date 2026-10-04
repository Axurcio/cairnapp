# ADR-003: ContextMemoryProvider abstraction

## Context
LLM-facing context retrieval is a fast-moving space (Graphiti, Hindsight, vector stores,
vendor memory APIs). Cairn's business logic must not depend on any one of them, and
memory must be erasable and rebuildable for consent and retention reasons.

## Decision
Define a provider-neutral `ContextMemoryProvider` protocol (`cairn/context/provider.py`):
`retain_event`, `recall`, `get_temporal_context`, `get_participant_context`,
`get_evidence_sources`, `forget_source`, `forget_journey`, `rebuild_journey`, `health`.
Items are keyed deterministically from canonical event ids and always return
`source_event_ids`. Ship `InMemoryContextProvider` (tests and local fallback) and
`GraphitiContextProvider`. Reserve `HindsightContextProvider` as a documented placeholder
that cannot be selected until it is evaluated. All providers must pass
`tests/contract/test_context_provider_contract.py`. Only `ContextProjectionService`
writes to a provider, and it reads canonical data first.

## Consequences
- Swapping or adding memory backends is an adapter plus the contract tests.
- Lowest-common-denominator API: provider-specific features need a protocol change.
- Recall is best effort: a provider outage degrades a turn, it does not break it.

## Status
Accepted
