"""HindsightContextProvider - FUTURE ADAPTER PLACEHOLDER.

Hindsight is being evaluated as an alternative agent-memory backend. This module
exists to (a) reserve the integration point and (b) document what an adapter must
honour. It is intentionally not selectable at runtime yet:
:func:`cairn.container.build_context_provider` refuses ``CAIRN_CONTEXT_PROVIDER=hindsight``.

An implementation must satisfy the :class:`~cairn.context.provider.ContextMemoryProvider`
protocol and the shared contract tests in ``tests/contract/test_context_provider_contract.py``:

* key every stored item by the deterministic ``ContextEvent.item_id`` so
  ``forget_source`` can find items from a canonical event id
* partition storage per (tenant, journey); never infer scope from stored data
* return canonical ``source_event_ids`` with every recalled item
* support full ``forget_journey`` + ``rebuild_journey`` from canonical events
"""

from __future__ import annotations

EVALUATION_STATUS = "not-implemented: evaluation pending (see docs/adr/ADR-003)"


class HindsightContextProvider:
    """Placeholder. Constructing it raises so it can never be used by accident."""

    name = "hindsight"

    def __init__(self) -> None:
        raise RuntimeError(f"HindsightContextProvider is a placeholder: {EVALUATION_STATUS}")
