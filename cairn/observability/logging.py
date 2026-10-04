"""Structured, privacy-aware logging.

Every log line is a JSON-compatible event carrying ``request_id`` and, where
known, ``tenant_id`` / ``journey_id`` (bound via :mod:`structlog.contextvars`).

Participant conversations, raw health information and media bytes must never be
logged by default. :func:`redact_sensitive` strips well-known sensitive keys from
every event unless ``CAIRN_LOG_SENSITIVE=true`` (refused in production).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace

SENSITIVE_KEYS = frozenset(
    {
        "text",
        "message_text",
        "content",
        "payload",
        "fields",
        "body",
        "answer",
        "rendered_text",
        "bytes",
        "data",
        "password",
        "secret",
        "api_key",
        "authorization",
    }
)
REDACTED = "[redacted]"

_allow_sensitive = False


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    if _allow_sensitive:
        return event_dict
    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
    return event_dict


def add_trace_context(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging(
    *, level: str = "INFO", json_output: bool = True, allow_sensitive: bool = False
) -> None:
    global _allow_sensitive
    _allow_sensitive = allow_sensitive

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_trace_context,
        redact_sensitive,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
    # Route stdlib logging (uvicorn, sqlalchemy, temporal) through a plain handler.
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")
    for noisy in ("neo4j", "httpx", "graphiti_core"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Neo4j query-planner advisories (e.g. "property key does not exist yet") are not errors.
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)


def bind_context(**values: Any) -> None:
    """Bind correlation identifiers (request/tenant/journey) for the current task."""
    structlog.contextvars.bind_contextvars(
        **{k: str(v) for k, v in values.items() if v is not None}
    )


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
