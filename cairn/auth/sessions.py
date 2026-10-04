"""Website sign-in: email + password accounts and server-side browser sessions.

A successful login issues a random bearer token for an HttpOnly cookie. Only its
SHA-256 is stored, so a database leak does not yield usable sessions. Each session
also carries a CSRF token that the browser must echo in ``X-CSRF-Token`` on every
state-changing request (see :mod:`cairn.api.deps`).

A session resolves to the same :class:`ActorContext` the rest of the platform
already understands, so authorization is unchanged: the tenant, roles and
participant come from the stored account, never from the request.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import timedelta

from cairn.auth.context import ActorContext, AuthenticationError, Role
from cairn.auth.passwords import dummy_hash, verify_password
from cairn.domain.models import LoginSession, UserAccount, utcnow
from cairn.persistence.repositories import Repositories

_INVALID_CREDENTIALS = "invalid email or password"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def actor_for(user: UserAccount) -> ActorContext:
    return ActorContext(
        actor_id=user.actor_id,
        tenant_id=user.tenant_id,
        participant_id=user.participant_id,
        roles=frozenset(Role(r) for r in user.roles),
    )


class SessionAuthService:
    def __init__(
        self, repos: Repositories, *, ttl: timedelta, request_id: str | None = None
    ) -> None:
        self._repos = repos
        self._ttl = ttl
        self._request_id = request_id

    async def login(
        self, email: str, password: str, *, replacing: str | None = None
    ) -> tuple[str, LoginSession, UserAccount]:
        """Verify credentials and open a session. Returns the raw token for the cookie.

        ``replacing`` is the browser's previous session token, revoked on success.
        """
        user = await self._repos.users.find_by_email(email.strip())
        # scrypt is CPU-bound: keep it off the event loop. Unknown emails still pay the
        # same cost so response time does not reveal which accounts exist.
        valid = await asyncio.to_thread(
            verify_password, password, user.password_hash if user else dummy_hash()
        )
        if user is None or not valid or not user.active:
            await self._audit_login(user, "denied", reason="invalid credentials")
            await self._repos.session.commit()
            raise AuthenticationError(_INVALID_CREDENTIALS)

        token = secrets.token_urlsafe(32)
        now = utcnow()
        login = await self._repos.login_sessions.add(
            LoginSession(
                user_id=user.id,
                token_hash=hash_token(token),
                csrf_token=secrets.token_urlsafe(32),
                created_at=now,
                expires_at=now + self._ttl,
            )
        )
        if replacing:
            previous = await self._repos.login_sessions.find_by_token_hash(hash_token(replacing))
            if previous is not None:
                await self._repos.login_sessions.revoke(previous.id, now)
        await self._repos.users.record_login(user.id, now)
        await self._audit_login(user, "completed")
        await self._repos.session.commit()
        return token, login, user

    async def resolve(self, token: str) -> tuple[UserAccount, LoginSession]:
        """Return the account and session for a cookie token, or raise if it is not usable."""
        login = await self._repos.login_sessions.find_by_token_hash(hash_token(token))
        if login is None or login.revoked_at is not None or login.expires_at <= utcnow():
            raise AuthenticationError("session expired or signed out")
        user = await self._repos.users.get(login.user_id)
        if user is None or not user.active:
            raise AuthenticationError("session expired or signed out")
        return user, login

    async def logout(self, login: LoginSession, user: UserAccount) -> None:
        await self._repos.login_sessions.revoke(login.id, utcnow())
        await self._repos.audit.record(
            tenant_id=user.tenant_id,
            actor_id=user.actor_id,
            action="session:logout",
            resource_type="user",
            resource_id=user.id,
            outcome="completed",
            request_id=self._request_id,
        )
        await self._repos.session.commit()

    async def _audit_login(
        self, user: UserAccount | None, outcome: str, *, reason: str | None = None
    ) -> None:
        # The attempted email is deliberately not recorded: it may be personal data
        # (or a password typed into the wrong field).
        await self._repos.audit.record(
            tenant_id=user.tenant_id if user else None,
            actor_id=user.actor_id if user else "anonymous",
            action="session:login",
            resource_type="user",
            resource_id=user.id if user else None,
            outcome=outcome,
            details={"reason": reason} if reason else None,
            request_id=self._request_id,
        )
