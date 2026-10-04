# ADR-004: Graphiti as a derived projection

## Context
Graphiti gives temporally aware knowledge graphs that are useful for AI retrieval. It is
tempting to treat it as the store of record, but graph extraction is LLM-driven,
non-deterministic, versioned by a third party, and hard to audit or selectively erase.

## Decision
Graphiti (on Neo4j) is a **derived, disposable projection** of canonical Postgres data.
- It receives only text rendered from committed canonical events.
- One `group_id` per (tenant, journey); scope always comes from canonical data.
- Episode ids are deterministic from canonical event ids, so a source event can be
  forgotten precisely and the whole journey can be rebuilt.
- It is never used for authorization and never holds the only copy of anything.
- Default `episodes` mode needs no LLM; `full` mode enables entity and fact extraction.
- Index creation runs once in the `migrate` job.

## Consequences
- Neo4j data loss is an inconvenience: run `POST /context/rebuild`.
- Graphiti upgrades or replacement do not risk canonical data.
- Projection is eventually consistent (seconds behind, via Temporal).
- Some duplication of data, which is accepted as the cost of a clean source of truth.

## Status
Accepted
