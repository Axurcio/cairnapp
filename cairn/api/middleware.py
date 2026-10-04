"""Request correlation and privacy-safe access logging."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from cairn.observability.logging import bind_context, clear_context, get_logger

log = get_logger("cairn.api")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        clear_context()
        bind_context(request_id=request_id, tenant_id=request.headers.get("x-cairn-tenant"))
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            route = request.scope.get("route")
            log.info(
                "http.request",
                method=request.method,
                # Route template, not the raw path, so identifiers are not logged twice.
                route=getattr(route, "path", request.url.path),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        response.headers["X-Request-ID"] = request_id
        clear_context()
        return response
