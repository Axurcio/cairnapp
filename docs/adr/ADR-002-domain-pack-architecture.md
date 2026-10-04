# ADR-002: Domain Pack architecture

## Context
Cairn must serve very different journeys (health evidence gathering, mentoring) without
forking the platform, and without letting domain configuration bypass platform controls
such as safety, consent or authorization.

## Decision
A Domain Pack is a versioned directory of YAML: a manifest, observation schemas, question
protocols, response policies, patterns, activities, a safety policy with approved
guidance, planner configuration, report templates and memory configuration. Packs contain
no executable code. Everything is validated by Pydantic schemas
(`cairn/domain_packs/schemas.py`) and cross-checked at load time (unknown fields, missing
questions, unapproved guidance, bad regexes). Packs and their artefacts use semantic
versions; journeys pin the pack version, compatible releases (same major) apply
automatically, and every decision records the version actually used. External
integrations are declared by packs but implemented as platform adapters.

## Consequences
- New domains need configuration, not platform changes.
- Decisions are traceable to exact rule versions.
- Expressiveness is limited to what the engines support. New rule types mean platform
  work, which is intentional.
- A pack linter (the contract tests) gives fast feedback to pack authors.

## Status
Accepted
