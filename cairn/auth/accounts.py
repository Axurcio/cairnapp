"""Provisioning website sign-in accounts.

Accounts are created by operators (``python -m cairn.auth.cli``) or the demo seed,
never by self-registration: who may act for which participant is a tenant decision.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from cairn.auth.context import Role
from cairn.auth.passwords import MIN_PASSWORD_LENGTH, hash_password
from cairn.domain.models import UserAccount
from cairn.persistence.repositories import Repositories


class AccountError(ValueError):
    pass


async def create_account(
    repos: Repositories,
    *,
    email: str,
    password: str,
    display_name: str,
    roles: set[Role],
    tenant_id: UUID | None,
    participant_id: UUID | None = None,
    actor_id: str | None = None,
) -> UserAccount:
    """Validate and add an account (the caller commits).

    ``actor_id`` defaults to the email. A facilitator's actor id must match the
    ``actor_id`` on their relationship rows for those relationships to apply.
    """
    email = email.strip().lower()
    if "@" not in email:
        raise AccountError("email must be an email address")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if not roles:
        raise AccountError("at least one role is required")
    if tenant_id is None and roles != {Role.PLATFORM_ADMIN}:
        raise AccountError("only platform_admin accounts may have no tenant")
    if tenant_id is not None and await repos.tenants.get(tenant_id) is None:
        raise AccountError("tenant not found")
    if Role.PARTICIPANT in roles:
        if participant_id is None or tenant_id is None:
            raise AccountError("participant accounts need a participant in the same tenant")
        if await repos.participants.get(tenant_id, participant_id) is None:
            raise AccountError("participant not found in this tenant")
    elif participant_id is not None:
        raise AccountError("only participant accounts may be linked to a participant")
    if await repos.users.find_by_email(email) is not None:
        raise AccountError("an account with this email already exists")

    return await repos.users.add(
        UserAccount(
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            password_hash=await asyncio.to_thread(hash_password, password),
            actor_id=actor_id or email,
            roles=sorted(r.value for r in roles),
            participant_id=participant_id,
        )
    )
