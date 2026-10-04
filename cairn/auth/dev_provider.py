"""Development authentication: identity from request headers.

NOT for production (settings validation refuses it). A real deployment replaces
this with an OIDC/JWT provider that produces the same :class:`ActorContext`.

Headers::

    X-Cairn-Actor:        actor id (required)
    X-Cairn-Tenant:       tenant UUID (required except for platform_admin)
    X-Cairn-Roles:        comma-separated roles, e.g. "participant"
    X-Cairn-Participant:  participant UUID (for participant actors)
    X-Cairn-Scopes:       optional comma-separated scope restriction
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from cairn.auth.context import ActorContext, AuthenticationError, Role


def _uuid(value: str | None, header: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise AuthenticationError(f"{header} must be a UUID") from exc


class DevAuthProvider:
    name = "dev"

    def authenticate(self, headers: Mapping[str, str]) -> ActorContext:
        actor_id = headers.get("x-cairn-actor")
        if not actor_id:
            raise AuthenticationError("missing X-Cairn-Actor header")
        try:
            roles = frozenset(
                Role(r.strip()) for r in headers.get("x-cairn-roles", "").split(",") if r.strip()
            )
        except ValueError as exc:
            raise AuthenticationError(f"unknown role in X-Cairn-Roles: {exc}") from exc
        tenant_id = _uuid(headers.get("x-cairn-tenant"), "X-Cairn-Tenant")
        if tenant_id is None and Role.PLATFORM_ADMIN not in roles:
            raise AuthenticationError("missing X-Cairn-Tenant header")
        participant_id = _uuid(headers.get("x-cairn-participant"), "X-Cairn-Participant")
        if Role.PARTICIPANT in roles and participant_id is None:
            raise AuthenticationError("participant actors require X-Cairn-Participant")
        raw_scopes = headers.get("x-cairn-scopes")
        scopes = (
            frozenset(s.strip() for s in raw_scopes.split(",") if s.strip()) if raw_scopes else None
        )
        return ActorContext(
            actor_id=actor_id,
            tenant_id=tenant_id,
            participant_id=participant_id,
            roles=roles,
            scopes=scopes,
        )
