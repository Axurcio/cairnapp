"""GraphitiContextProvider: Graphiti (on Neo4j) as a derived context projection.

Graphiti is NEVER canonical storage. This adapter only ever receives text that
was already committed to Postgres, keyed by deterministic item ids derived from
canonical event ids, so the whole projection can be dropped and rebuilt.

Partitioning: one Graphiti ``group_id`` per (tenant, journey). Scope is always
supplied by the caller from canonical data; Graphiti is never used to decide who
may see what.

Modes (``CAIRN_GRAPHITI_MODE``):

* ``episodes`` (default) - stores raw episodes only. Needs no LLM or embedder,
  so the default Docker Compose stack runs without credentials. Recall is
  recency + lexical overlap.
* ``full`` - ``Graphiti.add_episode`` performs entity/fact extraction and
  ``Graphiti.search`` does hybrid retrieval. Requires LLM + embedder credentials.

The ``graphiti_core`` import is confined to this module and :func:`create_graphiti_client`.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from cairn.context.provider import (
    ContextEvent,
    ContextItem,
    ContextItemKind,
    ContextScope,
    ProviderHealth,
    RebuildResult,
    RetainResult,
    SourceRef,
    context_item_id,
)
from cairn.observability.logging import get_logger

log = get_logger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")
_NAME = re.compile(r"^cairn:(?P<kind>[a-z_]+):(?P<event>[0-9a-f-]{36})$")


class _DropMessages(logging.Filter):
    def __init__(self, marker: str) -> None:
        super().__init__()
        self._marker = marker

    def filter(self, record: logging.LogRecord) -> bool:
        return self._marker not in record.getMessage()


def group_id_for(tenant_id: UUID, journey_id: UUID) -> str:
    """Graphiti group ids allow only [A-Za-z0-9_-]."""
    return f"cairn_{tenant_id.hex}_{journey_id.hex}"


def _episode_name(event: ContextEvent) -> str:
    return f"cairn:{event.kind.value}:{event.source_event_id}"


def _source_event_from_name(name: str) -> UUID | None:
    match = _NAME.match(name or "")
    return UUID(match.group("event")) if match else None


class GraphitiContextProvider:
    name = "graphiti"

    def __init__(self, graphiti: Any, *, mode: str = "episodes", recall_window: int = 200) -> None:
        self._graphiti = graphiti
        self._mode = mode
        self._recall_window = recall_window

    # The graphiti_core imports below are deferred so importing this module (and
    # therefore the whole application) never requires graphiti_core at import time.

    async def initialize(self) -> None:
        # Graphiti creates its indices concurrently; on an empty database these race and
        # log a benign EquivalentSchemaRuleAlreadyExists error before succeeding.
        driver_log = logging.getLogger("graphiti_core.driver.neo4j_driver")
        benign = _DropMessages("EquivalentSchemaRuleAlreadyExists")
        driver_log.addFilter(benign)
        try:
            await self._graphiti.build_indices_and_constraints()
        finally:
            driver_log.removeFilter(benign)

    async def retain_event(self, event: ContextEvent) -> RetainResult:
        from graphiti_core.nodes import EpisodeType, EpisodicNode

        group_id = group_id_for(event.scope.tenant_id, event.scope.journey_id)
        item_id = str(event.item_id)
        description = f"cairn {event.kind.value} ({event.domain_pack})"
        if self._mode == "full":
            await self._graphiti.add_episode(
                name=_episode_name(event),
                episode_body=event.text,
                source_description=description,
                reference_time=event.occurred_at,
                source=EpisodeType.message,
                group_id=group_id,
                uuid=item_id,
            )
        else:
            episode = EpisodicNode(
                uuid=item_id,
                name=_episode_name(event),
                group_id=group_id,
                labels=[],
                source=EpisodeType.text,
                source_description=description,
                content=event.text,
                valid_at=event.occurred_at,
                created_at=datetime.now(UTC),
            )
            await episode.save(self._graphiti.driver)
        return RetainResult(item_id=item_id, provider=self.name, created=True)

    async def _episodes(self, group_id: str, *, before: datetime, last_n: int) -> list[Any]:
        episodes: list[Any] = await self._graphiti.retrieve_episodes(
            reference_time=before, last_n=last_n, group_ids=[group_id]
        )
        return episodes

    def _episode_item(self, episode: Any, score: float | None = None) -> ContextItem:
        source = _source_event_from_name(episode.name)
        kind = episode.name.split(":")[1] if episode.name.count(":") == 2 else "episode"
        return ContextItem(
            item_id=str(episode.uuid),
            text=episode.content,
            kind=kind,
            occurred_at=episode.valid_at,
            score=score,
            source_event_ids=[source] if source else [],
            provider=self.name,
        )

    async def recall(self, scope: ContextScope, query: str, *, limit: int = 5) -> list[ContextItem]:
        group_id = group_id_for(scope.tenant_id, scope.journey_id)
        if self._mode == "full":
            edges = await self._graphiti.search(query, group_ids=[group_id], num_results=limit)
            return [
                ContextItem(
                    item_id=str(edge.uuid),
                    text=edge.fact,
                    kind="fact",
                    occurred_at=edge.valid_at,
                    source_event_ids=await self._sources_for_episodes(list(edge.episodes or [])),
                    provider=self.name,
                )
                for edge in edges
            ]
        wanted = set(_TOKEN.findall(query.lower()))
        episodes = await self._episodes(
            group_id, before=datetime.now(UTC), last_n=self._recall_window
        )
        scored = []
        for ep in episodes:
            overlap = len(wanted & set(_TOKEN.findall((ep.content or "").lower())))
            if overlap:
                scored.append((overlap / max(len(wanted), 1), ep))
        scored.sort(key=lambda s: (s[0], s[1].valid_at), reverse=True)
        return [self._episode_item(ep, round(score, 3)) for score, ep in scored[:limit]]

    async def _sources_for_episodes(self, episode_uuids: list[str]) -> list[UUID]:
        if not episode_uuids:
            return []
        from graphiti_core.nodes import EpisodicNode

        episodes = await EpisodicNode.get_by_uuids(self._graphiti.driver, episode_uuids)
        return [s for ep in episodes if (s := _source_event_from_name(ep.name))]

    async def get_temporal_context(
        self, scope: ContextScope, *, start: datetime, end: datetime, limit: int = 50
    ) -> list[ContextItem]:
        group_id = group_id_for(scope.tenant_id, scope.journey_id)
        episodes = await self._episodes(group_id, before=end, last_n=self._recall_window)
        in_range = sorted(
            (ep for ep in episodes if ep.valid_at >= start), key=lambda ep: ep.valid_at
        )
        return [self._episode_item(ep) for ep in in_range[:limit]]

    async def get_participant_context(
        self,
        tenant_id: UUID,
        participant_id: UUID,
        journey_ids: Sequence[UUID],
        *,
        limit: int = 20,
    ) -> list[ContextItem]:
        items: list[ContextItem] = []
        for journey_id in journey_ids:
            episodes = await self._episodes(
                group_id_for(tenant_id, journey_id), before=datetime.now(UTC), last_n=limit
            )
            items.extend(self._episode_item(ep) for ep in episodes)
        items.sort(key=lambda i: i.occurred_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return items[:limit]

    async def get_evidence_sources(
        self, scope: ContextScope, item_ids: Sequence[str]
    ) -> list[SourceRef]:
        from graphiti_core.nodes import EpisodicNode

        group_id = group_id_for(scope.tenant_id, scope.journey_id)
        episodes = await EpisodicNode.get_by_uuids(self._graphiti.driver, list(item_ids))
        refs = []
        for ep in episodes:
            source = _source_event_from_name(ep.name)
            if ep.group_id == group_id and source:
                refs.append(SourceRef(item_id=str(ep.uuid), source_event_ids=[source]))
        return refs

    async def forget_source(self, scope: ContextScope, source_event_id: UUID) -> int:
        from graphiti_core.nodes import EpisodicNode

        group_id = group_id_for(scope.tenant_id, scope.journey_id)
        candidates = [str(context_item_id(source_event_id, kind)) for kind in ContextItemKind]
        episodes = await EpisodicNode.get_by_uuids(self._graphiti.driver, candidates)
        # Only remove episodes inside the caller's (tenant, journey) partition.
        owned = [ep for ep in episodes if ep.group_id == group_id]
        for ep in owned:
            await self._graphiti.remove_episode(str(ep.uuid))
        return len(owned)

    async def forget_journey(self, tenant_id: UUID, journey_id: UUID) -> int:
        from graphiti_core.utils.maintenance.graph_data_operations import clear_data

        group_id = group_id_for(tenant_id, journey_id)
        records, _, _ = await self._graphiti.driver.execute_query(
            "MATCH (n {group_id: $group_id}) RETURN count(n) AS n", group_id=group_id
        )
        count = int(records[0]["n"]) if records else 0
        await clear_data(self._graphiti.driver, group_ids=[group_id])
        return count

    async def rebuild_journey(
        self, scope: ContextScope, events: Sequence[ContextEvent]
    ) -> RebuildResult:
        removed = await self.forget_journey(scope.tenant_id, scope.journey_id)
        for event in sorted(events, key=lambda e: e.occurred_at):
            await self.retain_event(event)
        return RebuildResult(provider=self.name, removed=removed, retained=len(events))

    async def health(self) -> ProviderHealth:
        try:
            await self._graphiti.driver.execute_query("RETURN 1 AS ok")
            return ProviderHealth(provider=self.name, healthy=True, detail=f"mode={self._mode}")
        except Exception as exc:
            return ProviderHealth(provider=self.name, healthy=False, detail=str(exc)[:200])

    async def aclose(self) -> None:
        await self._graphiti.close()


def create_graphiti_client(
    *,
    uri: str,
    user: str,
    password: str,
    mode: str,
    llm_api_key: str | None,
    llm_base_url: str | None,
    llm_model: str | None,
) -> Any:
    """Construct a Graphiti client without implicit credential lookups.

    In ``episodes`` mode no LLM is ever called, but Graphiti's constructor still
    builds OpenAI clients, so a placeholder key is supplied.
    """
    os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")
    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.llm_client import LLMConfig, OpenAIClient

    if mode == "full" and not llm_api_key:
        raise ValueError("CAIRN_GRAPHITI_MODE=full requires CAIRN_OPENAI_API_KEY")
    key = llm_api_key or "not-configured-episodes-mode"
    llm_config = LLMConfig(api_key=key, base_url=llm_base_url, model=llm_model)
    return Graphiti(
        uri,
        user,
        password,
        llm_client=OpenAIClient(config=llm_config),
        embedder=OpenAIEmbedder(OpenAIEmbedderConfig(api_key=key, base_url=llm_base_url)),
        cross_encoder=OpenAIRerankerClient(config=llm_config),
    )
