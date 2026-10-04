# Cairn architecture

This document explains how Cairn is put together and which rules every change must
keep. Each major decision has an ADR in [docs/adr/](docs/adr/).

## Core principles

1. **Canonical PostgreSQL data is authoritative.** Participants, journeys, the event
   log, observations, evidence metadata, goals, consent, relationships, permissions,
   pattern evaluations, next actions and audit state live in Postgres. If it matters,
   it is in Postgres. ([ADR-008](docs/adr/ADR-008-canonical-postgres-domain-model.md))

2. **Graphiti is a disposable, derived context projection.** It holds AI-retrievable
   context rendered from canonical events: temporal semantic context, entities, facts
   and relationships. It is never the only place important data lives, it is never used
   for authorization, and it can be deleted and rebuilt from Postgres at any time.
   ([ADR-003](docs/adr/ADR-003-context-memory-provider.md),
   [ADR-004](docs/adr/ADR-004-graphiti-derived-projection.md))

3. **Cairn determines decisions; LLMs do not control workflows.** An LLM may extract
   structure from language and phrase an already-decided response. It never selects a
   question, a policy, guidance, an action or a workflow transition.

4. **ResponsePolicy and QuestionProtocol are deterministic.** Given the same Domain Pack
   version and observation state, Cairn makes the same decision, and every decision
   states its policy id and version, Domain Pack version and reason.
   ([ADR-005](docs/adr/ADR-005-response-policy-engine.md))

5. **NeMo Guardrails are defence-in-depth.** They screen LLM inputs and outputs. They
   can only make Cairn more conservative (forcing approved template wording). They never
   decide authentication, tenant isolation, consent, authorization, data residency or
   application permissions. Cairn's own SafetyPolicy is authoritative.
   ([ADR-007](docs/adr/ADR-007-nemo-guardrails-boundary.md))

6. **Temporal manages durable workflows.** Long-running journey follow-ups, consent
   revocation, projection and rebuild run as Temporal workflows. Ordinary
   request/response logic does not. Workflow state holds ids and counters only, never
   domain records or message text. ([ADR-006](docs/adr/ADR-006-temporal-workflow-engine.md))

7. **Domain Packs are versioned.** Every pack and every artefact inside it (observation
   schema, question protocol, response policy, pattern, safety policy, planner config)
   has a semantic version, and decisions record the versions that produced them.
   Packs are data, not code. ([ADR-002](docs/adr/ADR-002-domain-pack-architecture.md))

8. **Health-related outputs remain descriptive** unless an approved product/regulatory
   profile explicitly permits otherwise. Health packs declare
   `regulatory_profile: descriptive_only`, prohibit diagnosis, treatment and prognosis
   claims in their SafetyPolicy, and may only say guidance that is listed, approved and
   (for clinical categories) human-reviewed. The contract tests enforce this.

## Process topology

Cairn starts as a **modular monolith plus worker processes**
([ADR-001](docs/adr/ADR-001-modular-monolith-first.md)). One codebase and one container
image run three process types:

```
  browser --> web (nginx: apps/web build, proxies /v1 on the same origin)
                            |
                 +----------v----------+         +----------------------+
  clients ---->  |  api (FastAPI)      |         |  worker (Temporal)   |
  (mobile, CLI)  |  cairn.api.main     |         |  cairn.workflows.    |
                 +----------+----------+         |  worker              |
                            |  start/signal      +----------+-----------+
                            +-------------> temporal <------+
                            |                (7233)          |
         +------------------+---------+--------------+-------+-----------+
         |                  |         |              |                   |
    PostgreSQL          Neo4j       MinIO        LLM endpoint       NeMo rails
    (canonical)     (Graphiti,    (evidence      (optional;         (optional,
                     derived)      binaries)      mock default)      in-process)
```

`migrate` is a one-shot job: Alembic migrations, then Graphiti index bootstrap.
The website (`apps/web`, React + Vite) is a separate static build served by nginx in
Compose; it holds no business logic and calls the same `/v1` API as every other client.

## Module boundaries

```
api ─────────► journeys ──► policies, patterns, planner, ai, guardrails, context(protocol)
  │               │
  └─► auth        └─► persistence (tenant-scoped repositories) ──► Postgres
workflows ──► activities ──► context.projection, evidence, reporting, persistence
container.py: the only module that picks concrete implementations
```

| Module | Owns | Depends on |
|---|---|---|
| `domain` | generic domain objects (no persistence, no HTTP) | nothing |
| `domain_packs` | pack schemas, loader, cross-reference validation, registry | `domain` |
| `policies` | ResponsePolicy engine, conditions, SafetyPolicy | `domain_packs` |
| `patterns` | PatternEngine and algorithm registry | `domain_packs` |
| `planner` | Planner, ResponseIntent | `policies` |
| `ai` | AIProvider protocol, mock and OpenAI-compatible providers, extraction, renderers | `planner` (intent type) |
| `guardrails` | GuardrailProvider, no-op, NeMo adapter and config | `planner` (intent type) |
| `context` | ContextMemoryProvider, in-memory, Graphiti, Hindsight placeholder, projection | `persistence` (projection only) |
| `evidence` | EvidenceStore, upload validation | nothing |
| `auth` | ActorContext, website accounts and sessions, dev auth, PolicyDecisionProvider, access checks, audit | `persistence` |
| `persistence` | ORM models, repositories, mapping to domain objects | `domain` |
| `journeys` | journey lifecycle, the message orchestration | most of the above (protocols only) |
| `workflows` | Temporal workflows, activities, dispatcher, worker | `context`, `evidence`, `reporting` |
| `api` | HTTP routes and API schemas | `journeys`, `auth` |

Vendor SDKs are confined: `graphiti_core` only in `context/graphiti.py`, `nemoguardrails`
only in `guardrails/nemo.py` (and the NeMo config's `actions.py`), `minio` only in
`evidence/store.py`, `temporalio` only in `workflows/`. LLM vendors are reached over
plain HTTP in `ai/openai_compatible.py`. Any of these modules could be extracted into a
service later without touching business logic.

## Three representations of data

| Layer | Example | Rule |
|---|---|---|
| Domain model | `cairn.domain.models.Observation` | what business logic reasons about |
| Persistence model | `cairn.persistence.models.ObservationRow` | never leaves `persistence/` |
| API model | `cairn.api.schemas.ObservationOut` | what clients see |

JSONB is used only for Domain-Pack-specific payloads (observation fields, event
payloads, decision explanations). Identity, tenancy, type and timing are real columns,
indexed on `tenant_id`, `journey_id`, `participant_id` and `occurred_at`.

## A participant turn

`JourneyMessageService.handle` ([cairn/journeys/message_service.py](cairn/journeys/message_service.py))
runs these steps explicitly. Each one is logged and listed in the response's
`explanation.trace`.

```
 1. authenticate               session cookie or dev auth → ActorContext (tenant from identity, never body)
 2. load journey + authorize   tenant-scoped query; PolicyDecisionProvider; consent check
 3. load Domain Pack           version-pinned (same major)            → domain_pack.loaded
 4. persist participant event  committed before any AI call           → journey.message.received
 5. safety input + guardrails  escalation triggers (deterministic); GuardrailProvider.validate_input
 6. recall context             ContextMemoryProvider.recall (consented, best effort)
 7. AI extraction              AIProvider.extract → raw JSON
 8. validate extraction        envelope + generated pack-schema models; bounded retry
                                                                      → observation.extracted
 9. update Observation         field-level provenance (event id, extractor, version)
10. evaluate patterns          PatternEngine (declarative rules)       → pattern.evaluated
11. evaluate ResponsePolicy    next missing field / complete / blocked → response_policy.evaluated
12. Planner                    candidates → constraints → priority     → planner.action.selected
13. SafetyPolicy (decision)    prohibited actions, approved/reviewed guidance
14. ResponseIntent             typed: kind, semantic intent, approved wording, limits
15. render                     template renderer (default) or LLM renderer with fallback
16. output validation          SafetyPolicy prohibited claims + GuardrailProvider.validate_output
                                                                      → guardrail.output.checked
17. persist                    NextAction (with full explanation) + assistant event
18. project context            WorkflowDispatcher → ContextProjectionWorkflow
                                                                      → context.projection.queued
19. notify JourneyWorkflow     signal-with-start; durable follow-up timer resets
```

If any check fails, Cairn falls back to more conservative behaviour: approved template
wording, then the pack's `safe_fallback_text`. It never falls back to unvalidated model
output.

### The decision chain

```
Observation fields ──► ResponsePolicyEngine ──► PolicyDecision
                                                 {ASK_QUESTION hand_shaking.duration,
                                                  policy hand_shaking_followup@1.0.0,
                                                  reason "required field duration is missing"}
PolicyDecision + PatternEvaluations + SafetySignal + history ──► Planner ──► PlannerDecision
                                                 {action, source, reason,
                                                  candidates[] with rejection reasons}
PlannerDecision ──► build_response_intent ──► ResponseIntent ──► Renderer ──► text
```

The Planner collects candidates from safety (ESCALATE), the journey (WAIT), the policy
(ASK_QUESTION, ACKNOWLEDGE, REQUEST_ACTIVITY, fallbacks for prohibited conditions),
patterns (REQUEST_ACTIVITY or REQUEST_EVIDENCE), and a default acknowledgement. It then
rejects candidates that break SafetyPolicy prohibitions, the session question budget,
the daily burden budget or cooldowns, and picks by the pack's `action_priority`. The
default acknowledgement only wins when nothing else is viable.

## Canonical events and provenance

- `journey_events` is append-only (the repository has no update or delete).
- Every observation records `source_event_ids`, `source_evidence_ids`,
  `extraction_version` and `field_provenance` (which event supplied each field, and which
  extractor and version produced it).
- PatternEvaluations record the rule id and version, algorithm and version, the
  contributing observations and their source events.
- NextActions store the full PolicyDecision and PlannerDecision as `explanation`.
- Reports are built deterministically from observations, and every statement lists its
  source events.
- Context items are keyed by `uuid5(event_id, kind)` and expose `source_event_ids`, so
  any recalled fact traces back to Postgres.

## Context memory

```
canonical commit ──► WorkflowDispatcher ──► ContextProjectionWorkflow ──► activity
                                                                           │
                       ContextProjectionService: load events by id (tenant-scoped),
                       check consent + journey status, render text ──► ContextMemoryProvider
```

- **Partitioning:** one Graphiti `group_id` per (tenant, journey). The caller always
  supplies scope from canonical data.
- **Modes:** `episodes` (default; raw episodes, no LLM) or `full` (Graphiti
  entity and fact extraction and hybrid search; needs LLM and embedder credentials).
- **Forget and rebuild:** `forget_source`, `forget_journey` and `rebuild_journey` are
  part of the contract. Consent revocation calls `forget_journey`, and
  `POST /context/rebuild` reconstructs the projection from Postgres.
- **Contract tests** in `tests/contract/test_context_provider_contract.py` define what any
  provider (including a future Hindsight adapter) must do.

## Safety layers

| Layer | Where | Authority |
|---|---|---|
| Domain Pack SafetyPolicy | `cairn/policies/safety.py` + `domain_packs/*/safety/` | **Authoritative**: escalation triggers, prohibited actions, approved and reviewed guidance, prohibited claims in output |
| Approved wording | pack templates, questions, guidance | Guidance is appended verbatim and never re-phrased by an LLM |
| GuardrailProvider (NeMo) | `cairn/guardrails/` | Defence-in-depth: deterministic rails by default, optional LLM self-check |
| Renderer limits | `cairn/ai/rendering.py` | Sentence budget and intent shape; otherwise fall back to the template |

## Authorization

- `ActorContext` (actor, tenant, participant, roles, scopes) comes from authentication:
  - **Website sessions** ([cairn/auth/sessions.py](cairn/auth/sessions.py)): an email +
    password account (`users`) is signed in to a server-side session (`login_sessions`).
    The HttpOnly cookie carries a random token (only its SHA-256 is stored); every
    POST must echo the session's CSRF token in `X-CSRF-Token`. The account row supplies
    tenant, roles and participant, so authorization is identical for every client.
  - **Dev headers** (`X-Cairn-*`) when `CAIRN_AUTH_PROVIDER=dev`; refused in production.
  - OIDC/JWT can later produce the same `ActorContext` without changing callers.
- Accounts are provisioned by operators (`python -m cairn.auth.cli create-user`); a
  facilitator account's `actor_id` must match its relationship rows.
- Repositories take `tenant_id` on every call. A resource in another tenant is
  indistinguishable from a missing one (404).
- `CairnPolicyDecisionProvider` enforces tenant boundary → role grants → own-data or
  active-relationship rules. The `PolicyDecisionProvider` protocol leaves room for an
  OPA-backed provider without changing callers.
- Access-sensitive reads and every denial are written to `audit_events`.

## Consent revocation

`POST /v1/journeys/{id}/consent/revoke` immediately marks consent revoked in Postgres, so
no new processing can start, then starts `ConsentRevocationWorkflow`:

1. mark consent revoked (idempotent)
2. restrict processing (journey → `processing_restricted`; pending questions blocked)
3. remove derived ContextMemoryProvider data (`forget_journey`)
4. delete or retain evidence by retention class (`retain_for_audit` is kept)
5. record the audit result

The canonical event log of what happened is kept; derived copies are removed.

## Observability

- structlog JSON logs with `request_id`, `tenant_id` and `journey_id` bound per request,
  plus `trace_id` and `span_id` when tracing is on.
- Keys such as `text`, `payload`, `fields` and `content` are redacted by default.
  Participant messages, media and raw health information are never logged unless
  `CAIRN_LOG_SENSITIVE=true`, which is refused in production.
- OpenTelemetry API spans (`journey.message`) are no-ops until `CAIRN_OTEL_ENABLED=true`.

## Extension points

| Want to... | Implement | Register in |
|---|---|---|
| Use another LLM | `AIProvider` | `container.build_ai_provider` |
| Use another memory backend | `ContextMemoryProvider` (pass the contract tests) | `container.build_context_provider` |
| Add a statistical pattern | `PatternAlgorithm` (EWMA, CUSUM, change-point...) | `patterns.engine.ALGORITHMS` |
| Use OPA for authorization | `PolicyDecisionProvider` | `container.build_container` |
| Store evidence elsewhere | `EvidenceStore` | `container.build_evidence_store` |
| Add a guardrail engine | `GuardrailProvider` | `container.build_guardrails` |
| Add a domain | a Domain Pack directory | `domain_packs/` |
