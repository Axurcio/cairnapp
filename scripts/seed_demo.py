"""Seed SYNTHETIC demo data: ``python scripts/seed_demo.py [--reset]``.

Everything created here is synthetic and labelled as such. No real patient or
person data is used. Historical turns are pushed through the real message
pipeline (with past ``occurred_at``), so observations, next actions, pattern
evaluations and context projections are produced exactly as in production.

Requires a migrated database (``make migrate``). Uses the configured context
provider (Graphiti in Docker Compose) but always projects inline, so the worker
does not need to be running.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from demo_ids import (
    ADMIN_ACTOR,
    DEMO_PASSWORD,
    HEALTH_JOURNEY_ID,
    HEALTH_PARTICIPANT_EMAIL,
    HEALTH_PARTICIPANT_ID,
    MENTOR_ACTOR,
    MENTORSHIP_JOURNEY_ID,
    MENTORSHIP_PARTICIPANT_EMAIL,
    MENTORSHIP_PARTICIPANT_ID,
    TENANT_ID,
    TENANT_NAME,
    admin_headers,
    participant_headers,
)
from sqlalchemy import delete

from cairn.auth.access import AccessService
from cairn.auth.accounts import create_account
from cairn.auth.context import ActorContext, Role
from cairn.config.settings import Environment, WorkflowDispatcherKind, get_settings
from cairn.container import Container, build_container
from cairn.domain.enums import ConsentScope, JourneyStatus, RelationshipType
from cairn.domain.models import Consent, Journey, Participant, Relationship, Tenant
from cairn.journeys.message_service import JourneyMessageService
from cairn.observability.logging import configure_logging
from cairn.persistence.models import TenantRow
from cairn.persistence.repositories import Repositories

HEALTH_HISTORY = [
    "My right hand has been shaky lately.",
    "About two months.",
    "Maybe a 3",
    "Most days",
    "Mostly when I'm holding my phone",
    "Writing takes a little longer than it used to",
]
MENTORSHIP_HISTORY_30_DAYS = [
    "I keep getting overlooked when projects are assigned.",
    "The data platform migration in March went to someone with less experience.",
    "Leading one cross-team project this year.",
    "I don't think my manager knows what I've been working on.",
]
MENTORSHIP_HISTORY_15_DAYS = ["I was passed over again for the new analytics project."]


async def _reset(container: Container) -> None:
    async with container.sessionmaker() as session:
        await session.execute(delete(TenantRow).where(TenantRow.id == TENANT_ID))
        await session.commit()
    for journey_id in (HEALTH_JOURNEY_ID, MENTORSHIP_JOURNEY_ID):
        await container.context.forget_journey(TENANT_ID, journey_id)
    print("Removed existing synthetic demo tenant and its derived context.")


async def _create_structure(container: Container) -> None:
    async with container.sessionmaker() as session:
        repos = Repositories(session)
        await repos.tenants.add(Tenant(id=TENANT_ID, name=TENANT_NAME))
        for pid, name, ref in (
            (HEALTH_PARTICIPANT_ID, "Synthetic Participant A (health demo)", "SYNTH-HEALTH-001"),
            (
                MENTORSHIP_PARTICIPANT_ID,
                "Synthetic Participant B (mentorship demo)",
                "SYNTH-MENTOR-001",
            ),
        ):
            await repos.participants.add(
                Participant(
                    id=pid,
                    tenant_id=TENANT_ID,
                    display_name=name,
                    external_ref=ref,
                    is_synthetic=True,
                )
            )
        for jid, pid, pack_id, title in (
            (
                HEALTH_JOURNEY_ID,
                HEALTH_PARTICIPANT_ID,
                "parkinsons",
                "Health evidence demo (SYNTHETIC)",
            ),
            (
                MENTORSHIP_JOURNEY_ID,
                MENTORSHIP_PARTICIPANT_ID,
                "mentorship",
                "Mentorship demo (SYNTHETIC)",
            ),
        ):
            pack = container.packs.get(pack_id)
            started = datetime.now(UTC) - timedelta(days=45)
            await repos.journeys.add(
                Journey(
                    id=jid,
                    tenant_id=TENANT_ID,
                    participant_id=pid,
                    title=title,
                    domain_pack=pack.id,
                    domain_pack_version=pack.version,
                    status=JourneyStatus.ACTIVE,
                    started_at=started,
                    is_synthetic=True,
                )
            )
            for scope in ConsentScope:
                await repos.consents.add(
                    Consent(
                        tenant_id=TENANT_ID,
                        participant_id=pid,
                        journey_id=jid,
                        scope=scope,
                        granted_at=started,
                        source="seed",
                    )
                )
        await repos.relationships.add(
            Relationship(
                tenant_id=TENANT_ID,
                participant_id=MENTORSHIP_PARTICIPANT_ID,
                actor_id=MENTOR_ACTOR,
                relationship_type=RelationshipType.MENTOR,
                journey_id=MENTORSHIP_JOURNEY_ID,
            )
        )
        await session.commit()


async def _ensure_demo_accounts(container: Container) -> None:
    """Website sign-in accounts for the synthetic demo (added to existing installs too)."""
    accounts = (
        (
            HEALTH_PARTICIPANT_EMAIL,
            "Synthetic Participant A",
            {Role.PARTICIPANT},
            HEALTH_PARTICIPANT_ID,
            f"participant:{HEALTH_PARTICIPANT_ID}",
        ),
        (
            MENTORSHIP_PARTICIPANT_EMAIL,
            "Synthetic Participant B",
            {Role.PARTICIPANT},
            MENTORSHIP_PARTICIPANT_ID,
            f"participant:{MENTORSHIP_PARTICIPANT_ID}",
        ),
        (MENTOR_ACTOR, "Demo Mentor", {Role.FACILITATOR}, None, MENTOR_ACTOR),
        (ADMIN_ACTOR, "Demo Tenant Admin", {Role.TENANT_ADMIN}, None, ADMIN_ACTOR),
    )
    async with container.sessionmaker() as session:
        repos = Repositories(session)
        for email, name, roles, participant_id, actor_id in accounts:
            if await repos.users.find_by_email(email) is None:
                await create_account(
                    repos,
                    email=email,
                    password=DEMO_PASSWORD,
                    display_name=name,
                    roles=roles,
                    tenant_id=TENANT_ID,
                    participant_id=participant_id,
                    actor_id=actor_id,
                )
        await session.commit()


async def _replay(
    container: Container,
    participant_id: object,
    journey_id: object,
    messages: list[str],
    when: datetime,
) -> None:
    actor = ActorContext(
        actor_id=f"participant:{participant_id}",
        tenant_id=TENANT_ID,
        participant_id=participant_id,  # type: ignore[arg-type]
        roles=frozenset({Role.PARTICIPANT}),
    )
    for offset, text in enumerate(messages):
        async with container.sessionmaker() as session:
            repos = Repositories(session)
            service = JourneyMessageService(
                repos=repos,
                access=AccessService(repos, container.authz),
                packs=container.packs,
                extraction=container.extraction,
                renderer=container.renderer,
                guardrails=container.guardrails,
                context=container.context,
                dispatcher=container.dispatcher,
            )
            result = await service.handle(
                actor,
                journey_id,  # type: ignore[arg-type]
                text,
                occurred_at=when + timedelta(minutes=2 * offset),
                source="seed",
            )
            print(f"    participant: {text}")
            print(f"    cairn:       {result.response_text}")


async def main(reset: bool) -> None:
    settings = get_settings()
    if settings.env is Environment.PRODUCTION:
        raise SystemExit("Refusing to seed synthetic demo data and accounts in production.")
    configure_logging(level="WARNING", json_output=False)
    # Project inline so seeding never depends on the Temporal worker being up.
    settings = settings.model_copy(update={"workflow_dispatcher": WorkflowDispatcherKind.INLINE})
    container = build_container(settings)
    try:
        await container.context.initialize()
        if reset:
            await _reset(container)
        async with container.sessionmaker() as session:
            if await Repositories(session).tenants.get(TENANT_ID):
                print("Synthetic demo data already present (use --reset to recreate).")
                await _ensure_demo_accounts(container)
                _print_summary()
                return

        await _create_structure(container)
        await _ensure_demo_accounts(container)
        now = datetime.now(UTC)
        print("Seeding SYNTHETIC health demo history (20 days ago):")
        await _replay(
            container,
            HEALTH_PARTICIPANT_ID,
            HEALTH_JOURNEY_ID,
            HEALTH_HISTORY,
            now - timedelta(days=20),
        )
        print("Seeding SYNTHETIC mentorship demo history (30 and 15 days ago):")
        await _replay(
            container,
            MENTORSHIP_PARTICIPANT_ID,
            MENTORSHIP_JOURNEY_ID,
            MENTORSHIP_HISTORY_30_DAYS,
            now - timedelta(days=30),
        )
        await _replay(
            container,
            MENTORSHIP_PARTICIPANT_ID,
            MENTORSHIP_JOURNEY_ID,
            MENTORSHIP_HISTORY_15_DAYS,
            now - timedelta(days=15),
        )
        print(f"Context provider: {container.context.name}")
        _print_summary()
    finally:
        await container.aclose()


def _print_summary() -> None:
    def h(headers: dict[str, str]) -> str:
        return " ".join(f"-H '{k}: {v}'" for k, v in headers.items())

    print(
        f"""
SYNTHETIC demo data ({TENANT_NAME})
  tenant_id:               {TENANT_ID}
  health journey:          {HEALTH_JOURNEY_ID}   (participant {HEALTH_PARTICIPANT_ID})
  mentorship journey:      {MENTORSHIP_JOURNEY_ID}   (participant {MENTORSHIP_PARTICIPANT_ID})
  tenant admin actor:      {ADMIN_ACTOR}

Website sign-in (password for every account: {DEMO_PASSWORD}):
  participant (health):     {HEALTH_PARTICIPANT_EMAIL}
  participant (mentorship): {MENTORSHIP_PARTICIPANT_EMAIL}
  mentor (facilitator):     {MENTOR_ACTOR}
  tenant admin:             {ADMIN_ACTOR}

Try:
  curl -s -X POST localhost:8000/v1/journeys/{HEALTH_JOURNEY_ID}/messages \\
    {h(participant_headers(HEALTH_PARTICIPANT_ID))} \\
    -H 'Content-Type: application/json' -d '{{"text": "My right hand has been shaky lately."}}'
  curl -s localhost:8000/v1/journeys/{HEALTH_JOURNEY_ID}/timeline {h(admin_headers())}
"""
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete and recreate demo data")
    asyncio.run(main(parser.parse_args().reset))
