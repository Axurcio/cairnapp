"""Deterministic PatternEngine.

Pattern rules are declarative (Domain Pack YAML). Each rule names an algorithm
from :data:`ALGORITHMS`; the engine filters candidate observations and delegates
the maths to that algorithm. Only ``occurrence_count`` ships today. Statistical
algorithms (EWMA, CUSUM, change-point detection, rolling regression, robust
percentiles) plug in by implementing :class:`PatternAlgorithm` over the same
:class:`ObservationPoint` series - no change to rules, engine or callers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from cairn.domain.models import Observation, PatternEvaluation, utcnow
from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.schemas import PatternRule
from cairn.policies.conditions import evaluate


@dataclass(frozen=True)
class ObservationPoint:
    observation_id: UUID
    occurred_at: datetime
    fields: dict[str, Any]
    source_event_ids: tuple[UUID, ...]
    source_evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class AlgorithmResult:
    matched: bool
    details: dict[str, Any]
    contributing: tuple[ObservationPoint, ...] = field(default=())


class PatternAlgorithm(Protocol):
    name: str
    version: str

    def evaluate(
        self, rule: PatternRule, points: Sequence[ObservationPoint], now: datetime
    ) -> AlgorithmResult: ...


class OccurrenceCountAlgorithm:
    """Matches when at least N qualifying observations occurred within the window."""

    name = "occurrence_count"
    version = "1.0.0"

    def evaluate(
        self, rule: PatternRule, points: Sequence[ObservationPoint], now: datetime
    ) -> AlgorithmResult:
        window_start = now - timedelta(days=rule.window_days)
        in_window = tuple(p for p in points if window_start <= p.occurred_at <= now)
        return AlgorithmResult(
            matched=len(in_window) >= rule.minimum_occurrences,
            details={
                "occurrences": len(in_window),
                "minimum_occurrences": rule.minimum_occurrences,
                "window_days": rule.window_days,
                "window_start": window_start.isoformat(),
                "window_end": now.isoformat(),
            },
            contributing=in_window,
        )


ALGORITHMS: dict[str, PatternAlgorithm] = {
    OccurrenceCountAlgorithm.name: OccurrenceCountAlgorithm(),
}


class UnknownPatternAlgorithm(LookupError):
    pass


class PatternEngine:
    def __init__(self, algorithms: dict[str, PatternAlgorithm] | None = None) -> None:
        self._algorithms = algorithms if algorithms is not None else ALGORITHMS

    def evaluate(
        self,
        pack: DomainPack,
        observation_type: str,
        observations: Sequence[Observation],
        *,
        tenant_id: UUID,
        journey_id: UUID,
        participant_id: UUID,
        now: datetime | None = None,
    ) -> list[PatternEvaluation]:
        now = now or utcnow()
        results: list[PatternEvaluation] = []
        for rule in pack.patterns_for(observation_type):
            algorithm = self._algorithms.get(rule.algorithm)
            if algorithm is None:
                raise UnknownPatternAlgorithm(rule.algorithm)
            points = [
                ObservationPoint(
                    observation_id=o.id,
                    occurred_at=o.occurred_at,
                    fields=o.fields,
                    source_event_ids=tuple(o.source_event_ids),
                    source_evidence_ids=tuple(o.source_evidence_ids),
                )
                for o in observations
                if o.observation_type == rule.observation_type
                and (rule.where is None or evaluate(rule.where, o.fields))
            ]
            outcome = algorithm.evaluate(rule, points, now)
            results.append(
                PatternEvaluation(
                    tenant_id=tenant_id,
                    journey_id=journey_id,
                    participant_id=participant_id,
                    occurred_at=now,
                    source="pattern_engine",
                    domain_pack=pack.id,
                    domain_pack_version=pack.version,
                    rule_id=rule.id,
                    rule_version=rule.version,
                    algorithm=algorithm.name,
                    algorithm_version=algorithm.version,
                    matched=outcome.matched,
                    result=outcome.details,
                    suggested_action=rule.action.suggest_next_action if outcome.matched else None,
                    evidence_refs=[p.observation_id for p in outcome.contributing],
                    source_event_ids=sorted(
                        {e for p in outcome.contributing for e in p.source_event_ids}, key=str
                    ),
                    evaluated_at=now,
                )
            )
        return results
