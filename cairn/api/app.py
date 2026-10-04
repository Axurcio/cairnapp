"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cairn import __version__
from cairn.api.errors import register_error_handlers
from cairn.api.middleware import RequestContextMiddleware
from cairn.api.routes import admin, auth, domain_packs, health, journeys
from cairn.config.settings import CairnSettings, get_settings
from cairn.container import Container, build_container
from cairn.observability.logging import configure_logging, get_logger
from cairn.observability.tracing import configure_tracing

log = get_logger(__name__)


def create_app(
    settings: CairnSettings | None = None, container: Container | None = None
) -> FastAPI:
    """Create the app. Tests pass a pre-built ``container``; otherwise one is built on startup."""
    settings = settings or (container.settings if container else get_settings())
    configure_logging(
        level=settings.log_level,
        json_output=settings.log_json,
        allow_sensitive=settings.log_sensitive,
    )
    configure_tracing(
        service_name=settings.service_name,
        enabled=settings.otel_enabled,
        console=settings.otel_console_exporter,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        app.state.container = container or build_container(settings)
        c: Container = app.state.container
        try:
            await c.context.initialize()
        except Exception as exc:
            # Derived context is optional: the API still serves canonical data.
            log.warning(
                "context.initialize.failed", provider=c.context.name, error=type(exc).__name__
            )
        log.info(
            "api.started",
            env=settings.env,
            ai_provider=c.ai.name,
            renderer=c.renderer.name,
            context_provider=c.context.name,
            guardrails=c.guardrails.name,
            dispatcher=c.dispatcher.name,
            domain_packs=[f"{p.id}@{p.version}" for p in c.packs.all()],
        )
        yield
        if owned:
            await c.aclose()

    app = FastAPI(
        title="Cairn API",
        version=__version__,
        lifespan=lifespan,
        description="Configurable platform for long-duration human-development "
        "and evidence-gathering journeys.",
    )
    if container is not None:
        app.state.container = container
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(journeys.router)
    app.include_router(domain_packs.router)
    return app
