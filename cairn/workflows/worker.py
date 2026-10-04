"""Temporal worker process: ``python -m cairn.workflows.worker``.

Same codebase and container image as the API (modular monolith, separate process).
"""

from __future__ import annotations

import asyncio
import signal

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from cairn.config.settings import get_settings
from cairn.container import build_container
from cairn.observability.logging import configure_logging, get_logger
from cairn.observability.tracing import configure_tracing
from cairn.workflows.workflows import WORKFLOWS

log = get_logger("cairn.worker")


async def _connect(address: str, namespace: str, attempts: int = 30) -> Client:
    for attempt in range(1, attempts + 1):
        try:
            return await Client.connect(
                address, namespace=namespace, data_converter=pydantic_data_converter
            )
        except Exception as exc:
            log.warning("worker.temporal.connect_retry", attempt=attempt, error=type(exc).__name__)
            await asyncio.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"could not connect to Temporal at {address}")


async def run() -> None:
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        json_output=settings.log_json,
        allow_sensitive=settings.log_sensitive,
    )
    configure_tracing(
        service_name=f"{settings.service_name}-worker",
        enabled=settings.otel_enabled,
        console=settings.otel_console_exporter,
    )
    container = build_container(settings)
    try:
        await container.context.initialize()
    except Exception as exc:
        log.warning("context.initialize.failed", error=type(exc).__name__)

    client = await _connect(settings.temporal_address, settings.temporal_namespace)
    acts = container.activities
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=WORKFLOWS,
        activities=[
            acts.project_events,
            acts.rebuild_context,
            acts.issue_reminder,
            acts.generate_report,
            acts.mark_consent_revoked,
            acts.restrict_processing,
            acts.forget_context,
            acts.apply_evidence_retention,
            acts.record_revocation_audit,
        ],
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info(
        "worker.started",
        task_queue=settings.temporal_task_queue,
        workflows=[w.__name__ for w in WORKFLOWS],
        context_provider=container.context.name,
    )
    async with worker:
        await stop.wait()
    log.info("worker.stopped")
    await container.aclose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
