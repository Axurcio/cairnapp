"""Liveness and readiness."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from cairn import __version__
from cairn.api.deps import get_container
from cairn.container import Container
from cairn.persistence.database import ping

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up. No dependencies are checked."""
    return {"status": "ok", "service": "cairn-api", "version": __version__}


@router.get("/ready")
async def ready(container: Container = Depends(get_container)) -> JSONResponse:
    """Readiness: canonical dependencies must be up; derived ones are reported."""
    checks: dict[str, Any] = {}
    try:
        await ping(container.engine)
        checks["database"] = {"healthy": True}
    except Exception as exc:
        checks["database"] = {"healthy": False, "detail": type(exc).__name__}
    checks["domain_packs"] = {
        "healthy": bool(container.packs.all()),
        "loaded": [f"{p.id}@{p.version}" for p in container.packs.all()],
    }
    context = await container.context.health()
    checks["context_memory"] = context.model_dump()
    checks["evidence_store"] = {
        "healthy": await container.evidence_store.health(),
        "provider": container.evidence_store.name,
    }
    checks["workflows"] = {
        "healthy": await container.dispatcher.health(),
        "dispatcher": container.dispatcher.name,
    }
    checks["ai_provider"] = {"provider": container.ai.name, "renderer": container.renderer.name}
    checks["guardrails"] = {"provider": container.guardrails.name}
    # Context memory is a derived projection: degraded, not unready, when it is down.
    critical = ("database", "domain_packs")
    ready_ = all(checks[name]["healthy"] for name in critical)
    degraded = [
        k for k in ("context_memory", "evidence_store", "workflows") if not checks[k]["healthy"]
    ]
    status = "ready" if ready_ and not degraded else ("degraded" if ready_ else "not_ready")
    return JSONResponse(
        status_code=200 if ready_ else 503, content={"status": status, "checks": checks}
    )
