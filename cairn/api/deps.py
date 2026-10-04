"""FastAPI dependencies: container, session, authenticated actor, services."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.auth.access import AccessService
from cairn.auth.context import ActorContext, AuthenticationError, AuthorizationError
from cairn.auth.sessions import SessionAuthService, actor_for
from cairn.config.settings import AuthProviderKind
from cairn.container import Container
from cairn.domain.models import LoginSession
from cairn.journeys.message_service import JourneyMessageService
from cairn.journeys.service import JourneyService
from cairn.observability.logging import bind_context
from cairn.persistence.repositories import Repositories

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-csrf-token"


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


async def get_session(
    container: Container = Depends(get_container),
) -> AsyncIterator[AsyncSession]:
    async with container.sessionmaker() as session:
        yield session


def get_request_id(request: Request) -> str | None:
    value: str | None = getattr(request.state, "request_id", None)
    return value


def get_repos(session: AsyncSession = Depends(get_session)) -> Repositories:
    return Repositories(session)


def get_session_auth(
    repos: Repositories = Depends(get_repos),
    container: Container = Depends(get_container),
    request_id: str | None = Depends(get_request_id),
) -> SessionAuthService:
    ttl = timedelta(hours=container.settings.session_ttl_hours)
    return SessionAuthService(repos, ttl=ttl, request_id=request_id)


def require_csrf(request: Request, login: LoginSession) -> None:
    """Cookies are sent automatically by the browser, so a state-changing request must also
    prove it came from our own page: a cross-site page cannot read the session's CSRF token."""
    if request.method in SAFE_METHODS:
        return
    supplied = request.headers.get(CSRF_HEADER, "")
    if not hmac.compare_digest(supplied.encode(), login.csrf_token.encode()):
        raise AuthorizationError("missing or invalid CSRF token")


async def get_actor(
    request: Request,
    container: Container = Depends(get_container),
    sessions: SessionAuthService = Depends(get_session_auth),
) -> ActorContext:
    """Authenticate the request: a browser session cookie, or (dev only) X-Cairn-* headers."""
    settings = container.settings
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        user, login = await sessions.resolve(token)
        require_csrf(request, login)
        actor = actor_for(user)
    elif settings.auth_provider is AuthProviderKind.DEV:
        actor = container.auth.authenticate(request.headers)
    else:
        raise AuthenticationError("sign in required")
    bind_context(tenant_id=actor.tenant_id)
    return actor


def get_access(
    repos: Repositories = Depends(get_repos),
    container: Container = Depends(get_container),
    request_id: str | None = Depends(get_request_id),
) -> AccessService:
    return AccessService(repos, container.authz, request_id=request_id)


def get_journey_service(
    repos: Repositories = Depends(get_repos),
    access: AccessService = Depends(get_access),
    container: Container = Depends(get_container),
    request_id: str | None = Depends(get_request_id),
) -> JourneyService:
    return JourneyService(
        repos, access, container.packs, container.dispatcher, request_id=request_id
    )


def get_message_service(
    repos: Repositories = Depends(get_repos),
    access: AccessService = Depends(get_access),
    container: Container = Depends(get_container),
) -> JourneyMessageService:
    return JourneyMessageService(
        repos=repos,
        access=access,
        packs=container.packs,
        extraction=container.extraction,
        renderer=container.renderer,
        guardrails=container.guardrails,
        context=container.context,
        dispatcher=container.dispatcher,
    )
