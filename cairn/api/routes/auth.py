"""Website sign-in: login, current session, logout.

The session token lives only in an HttpOnly cookie, so page scripts never see it.
The CSRF token returned here must be echoed in ``X-CSRF-Token`` on writes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from cairn.api.deps import get_container, get_repos, get_session_auth, require_csrf
from cairn.api.schemas import AccountOut, LoginRequest, SessionOut
from cairn.auth.context import AuthenticationError
from cairn.auth.sessions import SessionAuthService
from cairn.container import Container
from cairn.domain.models import LoginSession, UserAccount
from cairn.persistence.repositories import Repositories

router = APIRouter(prefix="/v1/auth", tags=["auth"])


async def _session_out(repos: Repositories, user: UserAccount, login: LoginSession) -> SessionOut:
    tenant = await repos.tenants.get(user.tenant_id) if user.tenant_id else None
    return SessionOut(
        account=AccountOut(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            actor_id=user.actor_id,
            roles=user.roles,
            tenant_id=user.tenant_id,
            tenant_name=tenant.name if tenant else None,
            participant_id=user.participant_id,
        ),
        csrf_token=login.csrf_token,
        expires_at=login.expires_at,
    )


@router.post("/login", response_model=SessionOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    sessions: SessionAuthService = Depends(get_session_auth),
    repos: Repositories = Depends(get_repos),
    container: Container = Depends(get_container),
) -> SessionOut:
    # Login CSRF is blocked because the body must be application/json (FastAPI's strict
    # content-type default): a cross-site page cannot send that without a CORS
    # preflight, which this API never grants.
    settings = container.settings
    token, login_session, user = await sessions.login(
        body.email, body.password, replacing=request.cookies.get(settings.session_cookie_name)
    )
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=int(settings.session_ttl_hours * 3600),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return await _session_out(repos, user, login_session)


@router.get("/session", response_model=SessionOut)
async def current_session(
    request: Request,
    sessions: SessionAuthService = Depends(get_session_auth),
    repos: Repositories = Depends(get_repos),
    container: Container = Depends(get_container),
) -> SessionOut:
    token = request.cookies.get(container.settings.session_cookie_name)
    if not token:
        raise AuthenticationError("sign in required")
    user, login_session = await sessions.resolve(token)
    return await _session_out(repos, user, login_session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    sessions: SessionAuthService = Depends(get_session_auth),
    container: Container = Depends(get_container),
) -> Response:
    settings = container.settings
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        try:
            user, login_session = await sessions.resolve(token)
        except AuthenticationError:
            pass  # already expired or revoked: just clear the cookie
        else:
            require_csrf(request, login_session)
            await sessions.logout(login_session, user)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
    return response
