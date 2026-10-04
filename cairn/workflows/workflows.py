"""Temporal workflows for long-running journey processes.

Temporal is used for durable, long-lived work (follow-ups over days, consent
revocation, projection rebuilds), not for ordinary request/response logic.
Workflow state holds ids and counters only.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from cairn.workflows.activities import CairnActivities
    from cairn.workflows.types import (
        ConsentRevocationInput,
        ConsentRevocationResult,
        JourneyRef,
        JourneyWorkflowInput,
        JourneyWorkflowStatus,
        ProjectionRequest,
    )

_RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), maximum_attempts=5)
_TIMEOUT = timedelta(minutes=2)


@workflow.defn(name="JourneyWorkflow")
class JourneyWorkflow:
    """One per journey. Waits for participant replies; issues bounded reminders on silence."""

    def __init__(self) -> None:
        self._status = JourneyWorkflowStatus()
        self._reply_pending = False

    @workflow.signal
    def participant_replied(self, event_id: str) -> None:
        self._status.replies += 1
        self._status.last_event_id = event_id
        self._reply_pending = True

    @workflow.signal
    def close(self) -> None:
        self._status.closed = True

    @workflow.query
    def status(self) -> JourneyWorkflowStatus:
        return self._status

    @workflow.run
    async def run(self, data: JourneyWorkflowInput) -> JourneyWorkflowStatus:
        ref = JourneyRef(tenant_id=data.tenant_id, journey_id=data.journey_id)
        reminders_since_reply = 0
        while not self._status.closed:
            try:
                await workflow.wait_condition(
                    lambda: self._reply_pending or self._status.closed,
                    timeout=timedelta(hours=data.follow_up_hours),
                )
            except TimeoutError:
                if reminders_since_reply < data.max_reminders:
                    await workflow.execute_activity_method(
                        CairnActivities.issue_reminder,
                        ref,
                        start_to_close_timeout=_TIMEOUT,
                        retry_policy=_RETRY,
                    )
                    reminders_since_reply += 1
                    self._status.reminders_issued += 1
                continue
            if self._reply_pending:
                self._reply_pending = False
                reminders_since_reply = 0
            if workflow.info().is_continue_as_new_suggested():
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(data)

        await workflow.execute_activity_method(
            CairnActivities.generate_report,
            ref,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        return self._status


@workflow.defn(name="ConsentRevocationWorkflow")
class ConsentRevocationWorkflow:
    """Revoke consent and propagate it to every derived store, then audit."""

    @workflow.run
    async def run(self, data: ConsentRevocationInput) -> ConsentRevocationResult:
        result = ConsentRevocationResult()
        # 1. mark consent revoked (canonical)
        result.revoked_consent_ids = await workflow.execute_activity_method(
            CairnActivities.mark_consent_revoked,
            data,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        # 2. prevent further relevant processing
        result.processing_restricted = await workflow.execute_activity_method(
            CairnActivities.restrict_processing,
            data,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        # 3. remove derived ContextMemoryProvider data
        result.context_items_removed = await workflow.execute_activity_method(
            CairnActivities.forget_context,
            data,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        # 4. remove/expire evidence according to retention rules
        deleted, retained = await workflow.execute_activity_method(
            CairnActivities.apply_evidence_retention,
            data,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        result.evidence_deleted, result.evidence_retained = deleted, retained
        # 5. record audit result
        result.audit_recorded = await workflow.execute_activity_method(
            CairnActivities.record_revocation_audit,
            args=[data, result],
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )
        return result


@workflow.defn(name="ContextProjectionWorkflow")
class ContextProjectionWorkflow:
    @workflow.run
    async def run(self, data: ProjectionRequest) -> int:
        return await workflow.execute_activity_method(
            CairnActivities.project_events,
            data,
            start_to_close_timeout=_TIMEOUT,
            retry_policy=_RETRY,
        )


@workflow.defn(name="ContextRebuildWorkflow")
class ContextRebuildWorkflow:
    @workflow.run
    async def run(self, data: JourneyRef) -> int:
        return await workflow.execute_activity_method(
            CairnActivities.rebuild_context,
            data,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=_RETRY,
        )


WORKFLOWS = [
    JourneyWorkflow,
    ConsentRevocationWorkflow,
    ContextProjectionWorkflow,
    ContextRebuildWorkflow,
]
