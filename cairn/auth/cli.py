"""Create website sign-in accounts.

    python -m cairn.auth.cli create-user --email ana@example.org --name "Ana" \\
        --role participant --tenant <tenant-uuid> --participant <participant-uuid>

The password is prompted for (or read from stdin with ``--password-stdin``) so it
never appears in shell history or the process list.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from uuid import UUID

from cairn.auth.accounts import AccountError, create_account
from cairn.auth.context import Role
from cairn.config.settings import get_settings
from cairn.persistence.database import create_engine, create_sessionmaker
from cairn.persistence.repositories import Repositories


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise AccountError("passwords do not match")
    return first


async def _create_user(args: argparse.Namespace) -> None:
    password = _read_password(args.password_stdin)
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine)() as session:
            repos = Repositories(session)
            user = await create_account(
                repos,
                email=args.email,
                password=password,
                display_name=args.name,
                roles={Role(r) for r in args.role},
                tenant_id=args.tenant,
                participant_id=args.participant,
                actor_id=args.actor_id,
            )
            await session.commit()
    finally:
        await engine.dispose()
    print(f"Created {user.email} (actor {user.actor_id}, roles {', '.join(user.roles)})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cairn.auth.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="create a website sign-in account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True, help="display name")
    create.add_argument(
        "--role",
        action="append",
        required=True,
        choices=[r.value for r in Role],
        help="repeat for several roles",
    )
    create.add_argument("--tenant", type=UUID, help="tenant id (omit only for platform_admin)")
    create.add_argument("--participant", type=UUID, help="participant id (participant role)")
    create.add_argument(
        "--actor-id", help="defaults to the email; must match facilitator relationships"
    )
    create.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)
    try:
        asyncio.run(_create_user(args))
    except AccountError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
