"""WorkflowDispatcher: how the API hands work to durable workflows.

* :class:`TemporalWorkflowDispatcher` starts Temporal workflows (Docker Compose).
* :class:`InlineWorkflowDispatcher` runs the same activity code in-process and
  synchronously - deterministic for tests and usable without Temporal. It has no
  durable timers, so journey follow-up reminders only exist under Temporal.
"""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import uuid4

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.contrib.pydantic import pydantic_data_converter

from cairn.observability.logging import get_logger
from cairn.workflows.activities import CairnActivities
from cairn.workflows.types import (
    ConsentRevocationInput,
    ConsentRevocationResult,
    JourneyRef,
    JourneyWorkflowInput,
    ProjectionRequest,
)
from cairn.workflows.workflows import (
    ConsentRevocationWorkflow,
    ContextProjectionWorkflow,
    ContextRebuildWorkflow,
    JourneyWorkflow,
)

log = get_logger(__name__)


class WorkflowDispatcher(Protocol):
    name: str

    async def project_events(self, req: ProjectionRequest) -> str: ...

    async def rebuild_context(self, ref: JourneyRef) -> str: ...

    async def revoke_consent(self, req: ConsentRevocationInput) -> str: ...

    async def journey_started(self, data: JourneyWorkflowInput) -> None: ...

    async def participant_replied(self, data: JourneyWorkflowInput, event_id: str) -> None: ...

    async def health(self) -> bool: ...

    async def aclose(self) -> None: ...


class InlineWorkflowDispatcher:
    name = "inline"

    def __init__(self, activities: CairnActivities) -> None:
        self._acts = activities
        self.last_revocation: ConsentRevocationResult | None = None

    async def project_events(self, req: ProjectionRequest) -> str:
        retained = await self._acts.project_events(req)
        return f"completed:{retained}"

    async def rebuild_context(self, ref: JourneyRef) -> str:
        retained = await self._acts.rebuild_context(ref)
        return f"completed:{retained}"

    async def revoke_consent(self, req: ConsentRevocationInput) -> str:
        # Same step order as ConsentRevocationWorkflow.
        result = ConsentRevocationResult()
        result.revoked_consent_ids = await self._acts.mark_consent_revoked(req)
        result.processing_restricted = await self._acts.restrict_processing(req)
        result.context_items_removed = await self._acts.forget_context(req)
        deleted, retained = await self._acts.apply_evidence_retention(req)
        result.evidence_deleted, result.evidence_retained = deleted, retained
        result.audit_recorded = await self._acts.record_revocation_audit(req, result)
        self.last_revocation = result
        return "completed"

    async def journey_started(self, data: JourneyWorkflowInput) -> None:
        log.info("workflow.inline.no_durable_timers", workflow="JourneyWorkflow")

    async def participant_replied(self, data: JourneyWorkflowInput, event_id: str) -> None:
        return None

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class TemporalWorkflowDispatcher:
    name = "temporal"

    def __init__(self, *, address: str, namespace: str, task_queue: str) -> None:
        self._address = address
        self._namespace = namespace
        self._task_queue = task_queue
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def client(self) -> Client:
        async with self._lock:
            if self._client is None:
                self._client = await Client.connect(
                    self._address,
                    namespace=self._namespace,
                    data_converter=pydantic_data_converter,
                )
            return self._client

    async def project_events(self, req: ProjectionRequest) -> str:
        client = await self.client()
        workflow_id = f"context-projection-{req.journey_id}-{req.event_ids[0]}"
        await client.start_workflow(
            ContextProjectionWorkflow.run,
            req,
            id=workflow_id,
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        return f"queued:{workflow_id}"

    async def rebuild_context(self, ref: JourneyRef) -> str:
        client = await self.client()
        workflow_id = f"context-rebuild-{ref.journey_id}"
        await client.start_workflow(
            ContextRebuildWorkflow.run,
            ref,
            id=workflow_id,
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        return f"queued:{workflow_id}"

    async def revoke_consent(self, req: ConsentRevocationInput) -> str:
        client = await self.client()
        workflow_id = f"consent-revocation-{req.journey_id}-{uuid4().hex[:8]}"
        await client.start_workflow(
            ConsentRevocationWorkflow.run, req, id=workflow_id, task_queue=self._task_queue
        )
        return f"queued:{workflow_id}"

    async def journey_started(self, data: JourneyWorkflowInput) -> None:
        client = await self.client()
        await client.start_workflow(
            JourneyWorkflow.run,
            data,
            id=f"journey-{data.journey_id}",
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )

    async def participant_replied(self, data: JourneyWorkflowInput, event_id: str) -> None:
        client = await self.client()
        # Signal-with-start: creates the journey workflow if it is not running yet.
        await client.start_workflow(
            JourneyWorkflow.run,
            data,
            id=f"journey-{data.journey_id}",
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            start_signal="participant_replied",
            start_signal_args=[event_id],
        )

    async def health(self) -> bool:
        try:
            client = await self.client()
            await client.service_client.check_health()
            return True
        except Exception:
            return False

    async def aclose(self) -> None:
        self._client = None
