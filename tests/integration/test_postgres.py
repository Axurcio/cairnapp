"""The message flow, tenancy and schema against real PostgreSQL."""

from __future__ import annotations

import httpx
from alembic import command
from alembic.config import Config

from cairn.config.settings import CairnSettings
from cairn.container import Container
from tests.conftest import REPO_ROOT, World, make_world


def test_migrations_match_models(migrated: CairnSettings) -> None:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", migrated.database_url)
    command.check(cfg)  # raises if the ORM and the migrated schema have drifted


async def test_health_flow_on_postgres(
    pg_client: httpx.AsyncClient, pg_container: Container
) -> None:
    world: World = await make_world(pg_container, "parkinsons", tenant_name="IT tenant")
    url = f"/v1/journeys/{world.journey_id}/messages"
    first = (
        await pg_client.post(
            url,
            json={"text": "My right hand has been shaky lately."},
            headers=world.participant_headers(),
        )
    ).json()
    assert first["next_action"]["question_id"] == "hand_shaking.duration"
    second = (
        await pg_client.post(
            url, json={"text": "About three months."}, headers=world.participant_headers()
        )
    ).json()
    assert second["observation"]["fields"]["duration"] == "P3M"
    assert second["next_action"]["question_id"] == "hand_shaking.severity"
    assert second["observation"]["source_event_ids"] == [
        first["participant_event_id"],
        second["participant_event_id"],
    ]


async def test_tenant_isolation_on_postgres(
    pg_client: httpx.AsyncClient, pg_container: Container
) -> None:
    a = await make_world(pg_container, "demo", tenant_name="IT tenant A")
    b = await make_world(pg_container, "demo", tenant_name="IT tenant B")
    response = await pg_client.get(f"/v1/journeys/{b.journey_id}", headers=a.admin_headers())
    assert response.status_code == 404
