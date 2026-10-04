# ADR-001: Modular monolith first

## Context
Cairn has many concerns (conversation orchestration, policy engines, context memory,
evidence, workflows, reporting) but one small team, an evolving domain and no proven
scaling hot spots. Splitting into microservices now would add network failure modes,
distributed transactions and deployment overhead before we know where the real seams are.

## Decision
Build one Python package (`cairn/`) with explicit module boundaries, shipped as one
container image that runs several process types: `api`, `worker` (Temporal) and the
one-shot `migrate` job. Modules talk through protocols (`AIProvider`,
`ContextMemoryProvider`, `GuardrailProvider`, `EvidenceStore`, `WorkflowDispatcher`,
`PolicyDecisionProvider`). Concrete implementations are chosen in one place,
`cairn/container.py`. Vendor SDKs are confined to single adapter modules.

## Consequences
- Simple local development: one image, one `docker compose up`.
- Refactoring across module boundaries is cheap while the domain is still moving.
- Extraction later is mechanical: a protocol already marks each seam.
- Discipline is needed to stop cross-module shortcuts; review should watch imports.

## Status
Accepted
