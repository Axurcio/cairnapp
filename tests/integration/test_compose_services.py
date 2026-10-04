"""MinIO evidence storage and Temporal workflows against the running Compose stack.

The Temporal tests need the ``worker`` service running (``make up``) because the
workflows execute there, sharing Postgres and Neo4j with this test process.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from cairn.config.settings import (
    CairnSettings,
    ContextProviderKind,
    WorkflowDispatcherKind,
)
from cairn.container import build_container, build_evidence_store
from cairn.context.provider import ContextScope
from cairn.domain.enums import ActorType, ConsentScope, EventType
from cairn.domain.models import ParticipantEvent
from cairn.evidence.store import MinioEvidenceStore
from cairn.persistence.repositories import Repositories
from cairn.workflows.dispatcher import TemporalWorkflowDispatcher
from cairn.workflows.types import ConsentRevocationInput, ProjectionRequest
from cairn.workflows.workflows import ConsentRevocationWorkflow
from tests.conftest import make_world


async def test_minio_evidence_store_roundtrip(migrated: CairnSettings) -> None:
    store = build_evidence_store(migrated)
    if not isinstance(store, MinioEvidenceStore):
        pytest.skip("CAIRN_EVIDENCE_STORE is not minio")
    key = f"integration/{uuid4()}"
    await store.put(key, b"synthetic evidence", "text/plain")
    assert await store.get(key) == b"synthetic evidence"
    await store.delete(key)
    assert await store.health()


@pytest.fixture
def temporal_settings(migrated: CairnSettings) -> CairnSettings:
    if migrated.workflow_dispatcher is not WorkflowDispatcherKind.TEMPORAL:
        pytest.skip("CAIRN_WORKFLOW_DISPATCHER is not temporal")
    if migrated.context_provider is not ContextProviderKind.GRAPHITI:
        pytest.skip("worker and tests must share the Graphiti projection")
    return migrated


async def test_projection_and_revocation_workflows_run_on_worker(
    temporal_settings: CairnSettings,
) -> None:
    container = build_container(temporal_settings)
    await container.context.initialize()
    dispatcher = container.dispatcher
    assert isinstance(dispatcher, TemporalWorkflowDispatcher)
    try:
        world = await make_world(container, "parkinsons", tenant_name="Temporal IT")
        async with container.sessionmaker() as session:
            event = await Repositories(session).events.append(
                ParticipantEvent(
                    tenant_id=world.tenant_id,
                    journey_id=world.journey_id,
                    participant_id=world.participant_id,
                    event_type=EventType.PARTICIPANT_MESSAGE,
                    actor_type=ActorType.PARTICIPANT,
                    payload={"text": "synthetic shaky hand note"},
                    consent_scope=ConsentScope.CONVERSATION,
                )
            )
            await session.commit()

        status = await dispatcher.project_events(
            ProjectionRequest(
                tenant_id=str(world.tenant_id),
                journey_id=str(world.journey_id),
                event_ids=[str(event.id)],
            )
        )
        workflow_id = status.split(":", 1)[1]
        client = await dispatcher.client()
        async with asyncio.timeout(60):
            retained = await client.get_workflow_handle(workflow_id).result()
        assert retained == 1
        scope = ContextScope(tenant_id=world.tenant_id, journey_id=world.journey_id)
        recalled = await container.context.recall(scope, "shaky hand")
        assert recalled[0].source_event_ids == [event.id]

        status = await dispatcher.revoke_consent(
            ConsentRevocationInput(
                tenant_id=str(world.tenant_id),
                journey_id=str(world.journey_id),
                scopes=["conversation"],
                requested_by="integration-test",
            )
        )
        async with asyncio.timeout(60):
            result = await client.get_workflow_handle_for(
                ConsentRevocationWorkflow.run, status.split(":", 1)[1]
            ).result()
        assert result.processing_restricted
        assert result.context_items_removed >= 1
        assert result.audit_recorded
        assert await container.context.recall(scope, "shaky hand") == []
    finally:
        await container.aclose()
