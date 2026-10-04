"""OpenTelemetry-ready tracing.

The application always creates spans through the OpenTelemetry API. Without
configuration the API is a no-op, so nothing is exported and no SaaS is needed.
Set ``CAIRN_OTEL_ENABLED=true`` to install an SDK tracer provider; standard
``OTEL_*`` environment variables (or the console exporter) control export.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_configured = False


def configure_tracing(*, service_name: str, enabled: bool, console: bool = False) -> None:
    global _configured
    if _configured or not enabled:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
