# ADR-008: Canonical Postgres domain model

## Context
Cairn needs a durable, auditable, tenant-isolated record of what actually happened,
generic enough to serve many Domain Packs, and queryable for timelines, reports and
patterns.

## Decision
PostgreSQL (with pgvector enabled for future use) is the canonical store, accessed via
SQLAlchemy 2 (async) and migrated with Alembic. Tables: `tenants`, `participants`,
`journeys`, `journey_events` (append-only), `observations`, `evidence` (metadata only;
binaries in object storage), `relationships`, `consents`, `pattern_evaluations`,
`next_actions`, `audit_events`. Identity, tenancy, typing and timing are columns, indexed
on `tenant_id`, `journey_id`, `participant_id` and `occurred_at`. JSONB holds only
Domain-Pack-specific payloads. Domain, persistence and API models are separate classes.
Repositories require `tenant_id` on every call. All ids are UUIDs.

## Consequences
- One source of truth for audit, reporting, rebuilding projections and retention.
- Generic tables mean domain meaning lives in Domain Pack schemas, so pack schema
  versions must be recorded (they are).
- Row-level security, encryption at rest and retention automation are production
  follow-ups (see docs/SECURITY.md).

## Status
Accepted
