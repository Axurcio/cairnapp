# Cairn

Cairn is a configurable platform for **long-duration human-development and
evidence-gathering journeys**: a participant talks to Cairn over weeks or months,
and Cairn turns what they say into structured, traceable evidence, asking the
right next question and nothing more.

Two reference **Domain Packs** ship with the scaffold:

| Pack | Purpose | Status |
|---|---|---|
| `parkinsons` | Health evidence gathering (descriptive only, never diagnostic) | SAMPLE, synthetic, not clinically reviewed |
| `mentorship` | Mentoring and career development | SAMPLE |
| `demo` | Non-clinical reading journal used by automated tests | Test fixture |

Two principles shape every design decision:

> **LLMs understand language and phrase responses. Deterministic application logic decides what should happen.**
>
> **Canonical Cairn data describes what actually happened. AI memory/context is a derived, replaceable projection.**

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full picture and [docs/adr/](docs/adr/) for the decisions behind it.

---

## Scaffold scope

**What works today** (each item is covered by tests or was checked against the running stack):

- FastAPI modular monolith plus a Temporal worker process, both built from one image
- Typed, generic domain model, kept separate from persistence (SQLAlchemy) and API models
- Domain Pack loader with strict schemas and cross-reference validation
- Deterministic engines: ResponsePolicy, QuestionProtocol, PatternEngine, Planner, SafetyPolicy
- `ResponseIntent` → renderer split (deterministic template renderer by default; optional LLM renderer)
- AI gateway: `MockAIProvider` (default, offline) and `OpenAICompatibleProvider`
- `ContextMemoryProvider` with in-memory and **Graphiti/Neo4j** implementations, plus a Hindsight placeholder
- `GuardrailProvider` with no-op and **NeMo Guardrails** implementations (NeMo is an optional extra)
- Postgres canonical store with Alembic migrations and pgvector enabled
- MinIO evidence storage behind `EvidenceStore`, with upload validation
- Temporal workflows: `JourneyWorkflow`, `ConsentRevocationWorkflow`, `ContextProjectionWorkflow`, `ContextRebuildWorkflow`
- **Website** ([apps/web](apps/web)): sign in, journeys, conversation, observations, report,
  evidence upload and consent withdrawal, for participants, facilitators and tenant admins
- Email + password accounts with server-side sessions (HttpOnly cookie, CSRF token), plus
  dev header auth for local tooling; both produce the same `ActorContext`
- Tenant-scoped repositories, audit trail (including sign-ins)
- Structured JSON logs with request/tenant/journey correlation and redaction of sensitive fields
- Docker Compose stack, VS Code Dev Container, Makefile, CI workflow

**Deliberately not built yet:** external identity (OIDC/SSO), password reset and account
self-service, login rate limiting, notification delivery, statistical
pattern algorithms, production Temporal and Neo4j topology, and the mobile app beyond a
placeholder shell. See [docs/SECURITY.md](docs/SECURITY.md) for production hardening TODOs.

---

## Quick start (Docker Compose)

You need Docker with Compose v2. No API keys are required.

```bash
docker compose up -d --build --wait   # or: make up
make seed                             # SYNTHETIC demo tenant, participants and history
make demo                             # runs the acceptance flows against the live API
```

Then open the website at **http://localhost:3000**. The sign-in page lists the synthetic
demo accounts: click one to sign in as that user (password `cairn-demo-only` for all).
The list appears only in the dev server and in builds made with `VITE_DEMO_ACCOUNTS=true`,
which the local Compose stack sets (`CAIRN_WEB_DEMO_ACCOUNTS=false` turns it off); a
plain production build does not contain these credentials at all.

| Account | Sees |
|---|---|
| `participant.health@smarttech.example` | their own health journey; can send messages, upload evidence, withdraw consent |
| `participant.mentorship@smarttech.example` | their own mentorship journey |
| `mentor.demo@smarttech.example` | the mentorship journey they mentor (read-only) |
| `admin.demo@smarttech.example` | every journey in the demo tenant (read-only conversation) |

`make demo` sends the scaffold's two reference conversations and checks Cairn's decisions:

```
[health] participant: My right hand has been shaky lately.
[health] cairn:       Thanks for telling me. How long have you noticed the shaking in your right hand?
[health] decision:    ASK_QUESTION hand_shaking.duration (hand_shaking_followup@1.0.0, pack parkinsons@0.1.0)
[health] participant: About three months.
[health] cairn:       On a scale from 0 to 10, how noticeable would you say it is?
[mentorship] participant: I keep getting overlooked when projects are assigned.
[mentorship] cairn:       Can you think of the most recent project you wanted to lead but weren't given the opportunity?
```

If a port is already taken on your machine, override it, for example
`POSTGRES_PORT=15432 CAIRN_API_PORT=18000 docker compose up -d`. Every port and
credential is listed in [.env.example](.env.example).

### Services and URLs

| Service | URL / port | Notes |
|---|---|---|
| Website | http://localhost:3000 | Sign in with a demo account (above); proxies `/v1` to the API |
| Cairn API | http://localhost:8000 | `GET /health`, `GET /ready` |
| API docs (OpenAPI) | http://localhost:8000/docs | Interactive Swagger UI |
| Temporal UI | http://localhost:8233 | Workflows: `journey-*`, `context-projection-*`, `consent-revocation-*` |
| Temporal gRPC | localhost:7233 | |
| Neo4j Browser | http://localhost:7474 | user `neo4j`, password `cairn_local_dev_only`; Bolt on 7687 |
| MinIO Console | http://localhost:9001 | user `cairn`, password `cairn_local_dev_only`; S3 API on 9000 |
| Postgres | localhost:5432 | db/user `cairn`, password `cairn_local_dev_only` |

All credentials are local-only defaults. Never reuse them anywhere else.

---

## VS Code Dev Container

1. Install VS Code and the **Dev Containers** extension (`ms-vscode-remote.remote-containers`).
2. Open this folder in VS Code.
3. Run **Dev Containers: Reopen in Container**.

VS Code builds `.devcontainer/Dockerfile` (Python 3.12, uv, Node.js 22, npm, git, curl,
psql), starts the `dev` service with Postgres, Neo4j, Temporal, Temporal UI and MinIO,
mounts the repo at `/workspace` and runs `.devcontainer/post-create.sh`, which installs
dependencies, applies migrations and bootstraps the Graphiti indices. The container runs
as the non-root `vscode` user and keeps shell history in a named volume.

Inside the container, services are reached by name (`postgres`, `neo4j`, `temporal`,
`minio`), and the `make` targets run directly against them:

```bash
make seed          # synthetic demo data
make api           # run the API with reload on :8000 (or use the "Cairn: API" debug config)
make worker        # run the Temporal worker locally
make web           # run the website with hot reload on :5173 (proxies /v1 to :8000)
make up            # alternatively start the containerised api + worker + web too
make test          # unit + contract tests
make integration   # tests against the real services
```

The API and worker containers are not started automatically in the Dev Container, so
you can run and debug them from VS Code instead. VS Code tasks (**Terminal → Run Task**)
cover the common operations: *Cairn: Compose Up/Down, API Tests, All Tests, Ruff, Type
Check, Alembic Upgrade, Seed Demo Data, Run Worker, Run Website*.

---

## Tests and checks

```bash
make test          # unit + contract: no Docker, no network, no API keys (about 3s)
make lint          # ruff check + ruff format --check
make typecheck     # mypy --strict over the cairn package
make check         # all of the above (what CI's first job runs)
make web-check     # website: TypeScript, unit tests (vitest) and production build
make integration   # needs `make up`: Postgres, Neo4j/Graphiti, MinIO, Temporal + worker
```

- **Unit tests** run the real ORM on in-memory SQLite with `MockAIProvider`, the template
  renderer, in-memory context and inline workflows.
- **Contract tests** check every `ContextMemoryProvider` (in-memory always; Graphiti when
  `CAIRN_INTEGRATION=1`) and every shipped Domain Pack against shared contracts.
- **Integration tests** cover Alembic drift (`alembic check`), the message flow on Postgres,
  MinIO round-trips, and workflows executing on the Compose worker.

---

## Database migrations

```bash
make migrate                          # alembic upgrade head + Graphiti index bootstrap
make migration m="add goals table"    # autogenerate a new revision (review it before committing)
```

In Compose, the one-shot `migrate` service runs before the API and worker start.
Migrations live in [migrations/versions/](migrations/versions/). They do not import
application types, so they stay valid as the code evolves.

---

## Inspecting the moving parts

- **Temporal:** open http://localhost:8233. Each journey has a long-running
  `journey-<journey_id>` workflow (signal-with-start on every participant message).
  Projections run as `context-projection-*`, revocations as `consent-revocation-*`.
  CLI: `docker compose exec temporal temporal workflow list --address localhost:7233`.
- **Neo4j (Graphiti projection):** open http://localhost:7474 and run
  `MATCH (e:Episodic) RETURN e.group_id, e.name, e.content LIMIT 25`.
  Each journey is one Graphiti `group_id` (`cairn_<tenant>_<journey>`), and each episode
  name embeds the canonical event id it came from.
- **MinIO:** open http://localhost:9001 and browse the `cairn-evidence` bucket. Object keys
  are `<tenant_id>/<journey_id>/<evidence_id>` and never contain client-supplied names.
- **Decisions:** every `POST /v1/journeys/{id}/messages` response includes `explanation`
  (policy decision, planner candidates with rejection reasons, ResponseIntent, safety
  and guardrail results, and a step trace). `GET /v1/journeys/{id}/next-actions` lists
  persisted decisions.

### Calling the API

Development auth reads identity from headers (refused when `CAIRN_ENV=production`):

```bash
T=e81b0f63-69e0-5d56-bbae-b23c8ece770e      # seeded demo tenant (deterministic ids)
J=14e4d82f-7104-54af-985f-dc93932ef2a5      # seeded health journey
P=03e57082-005b-5697-ae0c-16d8c1a755af      # its synthetic participant

curl -s -X POST localhost:8000/v1/journeys/$J/messages \
  -H "X-Cairn-Actor: participant:$P" -H "X-Cairn-Tenant: $T" \
  -H "X-Cairn-Roles: participant" -H "X-Cairn-Participant: $P" \
  -H 'Content-Type: application/json' \
  -d '{"text": "My right hand has been shaky lately."}' | jq '.response.text, .next_action'
```

Roles: `platform_admin` (create tenants), `tenant_admin`, `facilitator` (needs an active
relationship with the participant), `participant` (own data only). The tenant always comes
from the authenticated actor, never from a request body.

Header identities are accepted only while `CAIRN_AUTH_PROVIDER=dev` (the local default).
Set it to `session` to require website sign-in; production refuses `dev`.

---

## Website and sign-in

The website ([apps/web](apps/web)) is a React + Vite app. It is a client of the `/v1` API
like any other; all decisions and authorization stay in the API.

- **Sign-in:** `POST /v1/auth/login` checks an email + password (scrypt hash) and sets an
  HttpOnly, SameSite=Lax session cookie. Only a SHA-256 of the session token is stored
  (`login_sessions`). `GET /v1/auth/session` restores the session after a reload;
  `POST /v1/auth/logout` revokes it. Sessions expire after `CAIRN_SESSION_TTL_HOURS` (12).
- **CSRF:** the login response carries a `csrf_token`; every POST made with the cookie must
  send it as `X-CSRF-Token`, or the API answers 403.
- **Same origin:** nginx (Compose) or the Vite dev server proxies `/v1`, so no CORS is
  needed or enabled. Behind HTTPS set `CAIRN_SESSION_COOKIE_SECURE=true` (required in
  production).
- **What a user sees** follows the existing rules: `GET /v1/journeys` lists a tenant
  admin's whole tenant, a participant's own journeys, and the journeys a facilitator has
  an active relationship with. Only the participant can send messages and upload evidence.

### Creating accounts

There is no self-registration: accounts are provisioned by an operator. Each account
belongs to one tenant and maps onto an `ActorContext`:

```bash
# participant (linked to a participant record in the tenant)
uv run python -m cairn.auth.cli create-user --email ana@example.org --name "Ana" \
  --role participant --tenant <tenant-id> --participant <participant-id>

# facilitator: --actor-id must match the actor_id on their relationship rows (defaults to the email)
uv run python -m cairn.auth.cli create-user --email mentor@example.org --name "Sam" \
  --role facilitator --tenant <tenant-id>
```

The password is prompted for (`--password-stdin` for scripts) and must be at least 12
characters. In Compose, run it with `docker compose exec api python -m cairn.auth.cli ...`.

---

## Domain Packs

A Domain Pack is **configuration, schemas and rules; never code**. It lives in
`domain_packs/<pack_id>/`:

```
manifest.yaml        id, semantic version, classification, regulatory profile, terminology
observations/        observation schemas (typed fields) + optional mock-extraction hints
questions/           QuestionProtocols: what each question collects, intent, wording, skip rules
responses/           ResponsePolicies: triggers, required fields, priority, branches,
                     prohibited conditions, completion, approved templates, LLM limits
patterns/            declarative pattern rules (algorithm, window, threshold, suggested action)
activities/          activities Cairn may request
safety/              SafetyPolicy (prohibited claims, escalation triggers) + approved guidance
planner/             action priority, burden budgets, session limits, follow-up interval
reports/             descriptive report templates
memory/              what is projected into derived context memory
```

**ResponsePolicies live in `domain_packs/<pack>/responses/`**, and the questions they ask
live in `domain_packs/<pack>/questions/`. For example, see
[hand_shaking_followup.yaml](domain_packs/parkinsons/responses/hand_shaking_followup.yaml).

### Adding a Domain Pack

1. Copy `domain_packs/demo` to `domain_packs/<new_id>` and set `id` (it must match the
   directory) and `version` (semver) in `manifest.yaml`.
2. Define observation schemas, then the questions that collect each required field.
3. Write a ResponsePolicy per observation type, approved templates and guidance, and
   safety rules (prohibited claims, escalation triggers).
4. Validate: `make test` runs the Domain Pack contract (cross-references, semver, and a
   check that no approved wording breaks the pack's own safety rules). A broken pack
   fails at load time with a list of problems.
5. Restart the API; the pack appears in `GET /v1/domain-packs`.

Journeys pin the pack version they started on. A compatible release (same major
version) is picked up automatically and every decision records the version actually
used; a new major version needs an explicit migration.

---

## Canonical data vs Graphiti

| | Canonical (PostgreSQL) | Derived (Graphiti on Neo4j) |
|---|---|---|
| Role | Source of truth: what actually happened | Retrieval-optimised context for AI |
| Holds | participants, journeys, events, observations, evidence metadata, consents, relationships, decisions, audit | episodes (and in `full` mode, entities and facts) rendered from canonical events |
| Written by | the application, in transactions | only `ContextProjectionService`, after the canonical commit |
| Used for authorization? | Yes | **Never** |
| Can be deleted? | Only by retention rules | Any time: `POST /v1/journeys/{id}/context/rebuild` recreates it |

Business code depends only on the `ContextMemoryProvider` protocol
([cairn/context/provider.py](cairn/context/provider.py)); `graphiti_core` is imported in
exactly one module ([cairn/context/graphiti.py](cairn/context/graphiti.py)). Every context
item carries the canonical event ids it came from.

Graphiti runs in `episodes` mode by default, which stores raw episodes and needs no LLM.
Set `CAIRN_GRAPHITI_MODE=full` with `CAIRN_OPENAI_API_KEY` to enable Graphiti's entity
and fact extraction.

---

## Configuration

All settings are `CAIRN_*` environment variables ([cairn/config/settings.py](cairn/config/settings.py)):

| Setting | Default (Compose) | Options |
|---|---|---|
| `CAIRN_AI_PROVIDER` | `mock` | `mock`, `openai_compatible` (+ `CAIRN_OPENAI_BASE_URL/API_KEY/MODEL`) |
| `CAIRN_RENDERER` | `template` | `template`, `llm` |
| `CAIRN_CONTEXT_PROVIDER` | `graphiti` | `graphiti`, `in_memory` |
| `CAIRN_GRAPHITI_MODE` | `episodes` | `episodes`, `full` |
| `CAIRN_GUARDRAIL_PROVIDER` | `noop` | `noop`, `nemo` (build with `CAIRN_EXTRAS=nemo`) |
| `CAIRN_EVIDENCE_STORE` | `minio` | `minio`, `local` |
| `CAIRN_WORKFLOW_DISPATCHER` | `temporal` | `temporal`, `inline` |

To enable NeMo Guardrails: `CAIRN_EXTRAS=nemo CAIRN_GUARDRAIL_PROVIDER=nemo docker compose up -d --build`.
The shipped rails in [cairn/guardrails/nemo_config/](cairn/guardrails/nemo_config/) are
deterministic and need no LLM; LLM self-check rails can be switched on in `config.yml`.

---

## Repository layout

```
apps/api/            Dockerfile for the single app image (API, worker, migrate job)
apps/web/            React + Vite website (sign-in, journeys, conversation); nginx image
apps/mobile/         Expo placeholder shell
cairn/               platform core (one package, clear module boundaries)
  api/               FastAPI app, routes, API schemas, middleware
  auth/              ActorContext, accounts + sessions, dev auth, PolicyDecisionProvider, access checks
  config/            typed settings
  domain/            generic domain model
  domain_packs/      pack schemas, loader, registry
  policies/          ResponsePolicy engine, conditions, SafetyPolicy
  patterns/          PatternEngine and algorithms
  planner/           Planner and ResponseIntent
  ai/                AI gateway, extraction, renderers, providers
  guardrails/        GuardrailProvider, NeMo adapter and config
  context/           ContextMemoryProvider, in-memory, Graphiti, Hindsight placeholder, projection
  evidence/          EvidenceStore implementations and upload validation
  journeys/          journey lifecycle and message orchestration
  events/            the canonical append-only event log
  reporting/         descriptive, provenance-linked reports
  workflows/         Temporal workflows, activities, dispatcher, worker
  persistence/       ORM models, tenant-scoped repositories
  observability/     structured logging, tracing
domain_packs/        demo, mentorship, parkinsons
migrations/          Alembic
scripts/             seed_demo.py, demo_flow.py
tests/               unit, contract, integration
docs/adr/            architecture decision records
```
