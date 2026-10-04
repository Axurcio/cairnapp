"""Map domain/business exceptions onto HTTP responses."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cairn.auth.access import NotFound
from cairn.auth.context import AuthenticationError, AuthorizationError
from cairn.domain_packs.registry import DomainPackNotFound, DomainPackVersionMismatch
from cairn.evidence.validation import EvidenceValidationError
from cairn.journeys.errors import JourneyError


def _json(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def _authn(_: Request, exc: AuthenticationError) -> JSONResponse:
        return _json(401, str(exc))

    @app.exception_handler(AuthorizationError)
    async def _authz(_: Request, exc: AuthorizationError) -> JSONResponse:
        return _json(403, f"forbidden: {exc.reason}")

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
        # Same response for "does not exist" and "exists in another tenant".
        return _json(404, f"{exc} not found")

    @app.exception_handler(DomainPackNotFound)
    async def _pack(_: Request, exc: DomainPackNotFound) -> JSONResponse:
        return _json(404, f"domain pack '{exc}' not found")

    @app.exception_handler(DomainPackVersionMismatch)
    async def _pack_version(_: Request, exc: DomainPackVersionMismatch) -> JSONResponse:
        return _json(409, str(exc))

    @app.exception_handler(JourneyError)
    async def _journey(_: Request, exc: JourneyError) -> JSONResponse:
        return _json(exc.status_code, exc.detail)

    @app.exception_handler(EvidenceValidationError)
    async def _evidence(_: Request, exc: EvidenceValidationError) -> JSONResponse:
        return _json(exc.status_code, exc.reason)
