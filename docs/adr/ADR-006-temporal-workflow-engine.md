# ADR-006: Temporal for durable workflows

## Context
Journeys last months: follow-up reminders after silence, consent revocation that must
complete across several stores, projection and rebuild jobs that must retry. Cron jobs
and ad-hoc queues make these brittle and hard to observe.

## Decision
Use Temporal (Python SDK) for durable, long-running processes: `JourneyWorkflow`
(one per journey; signal-with-start on each reply; bounded reminders on durable timers),
`ConsentRevocationWorkflow`, `ContextProjectionWorkflow` and `ContextRebuildWorkflow`.
Activities take ids, read Postgres and return small results. Workflow state never holds
domain records, message text or evidence. Request/response logic stays in the API.
A `WorkflowDispatcher` protocol hides Temporal from the API. An inline dispatcher runs
the same activity code synchronously for tests. Local development uses the Temporal dev
server (SQLite on a volume); production needs a real cluster.

## Consequences
- Retries, timers and visibility (Temporal UI) for free.
- Another runtime to operate in production.
- Workflow code must stay deterministic (sandboxed; imports passed through).

## Status
Accepted
