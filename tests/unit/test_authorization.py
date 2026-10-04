"""Tenant isolation and access checks (no IDOR)."""

from __future__ import annotations

from uuid import uuid4

import httpx

from cairn.container import Container
from cairn.persistence.models import AuditEventRow
from tests.conftest import World


async def test_d_tenant_a_cannot_read_tenant_b_journey(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    a: World = await world_factory("demo", tenant_name="Tenant A")
    b: World = await world_factory("demo", tenant_name="Tenant B")

    own = await client.get(f"/v1/journeys/{a.journey_id}", headers=a.admin_headers())
    assert own.status_code == 200

    for path in ("", "/timeline", "/observations", "/next-actions", "/report"):
        response = await client.get(f"/v1/journeys/{b.journey_id}{path}", headers=a.admin_headers())
        # Not 403: other tenants' resources are indistinguishable from missing ones.
        assert response.status_code == 404, path

    posted = await client.post(
        f"/v1/journeys/{b.journey_id}/messages",
        json={"text": "hi"},
        headers=a.participant_headers(),
    )
    assert posted.status_code == 404


async def test_participant_cannot_read_another_participants_journey(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    a: World = await world_factory("demo")
    # Same tenant as `a`, but authenticated as a different participant.
    intruder = {**a.participant_headers(), "X-Cairn-Participant": str(uuid4())}
    response = await client.get(f"/v1/journeys/{a.journey_id}", headers=intruder)
    assert response.status_code == 403

    async with container.sessionmaker() as session:
        denied = (
            await session.execute(
                AuditEventRow.__table__.select().where(AuditEventRow.outcome == "denied")
            )
        ).all()
    assert denied, "denied access must be audited"


async def test_tenant_comes_from_actor_not_body(client: httpx.AsyncClient, world_factory) -> None:  # type: ignore[no-untyped-def]
    a: World = await world_factory("demo", tenant_name="Tenant A")
    b: World = await world_factory("demo", tenant_name="Tenant B")
    # A tenant-A admin cannot create a journey for a tenant-B participant.
    response = await client.post(
        "/v1/journeys",
        headers=a.admin_headers(),
        json={"participant_id": str(b.participant_id), "domain_pack": "demo", "title": "x"},
    )
    assert response.status_code == 404


async def test_facilitator_requires_relationship(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    from cairn.domain.enums import RelationshipType
    from cairn.domain.models import Relationship
    from cairn.persistence.repositories import Repositories

    world: World = await world_factory("mentorship")
    headers = {
        "X-Cairn-Actor": "mentor-1",
        "X-Cairn-Tenant": str(world.tenant_id),
        "X-Cairn-Roles": "facilitator",
    }
    url = f"/v1/journeys/{world.journey_id}"
    assert (await client.get(url, headers=headers)).status_code == 403

    async with container.sessionmaker() as session:
        await Repositories(session).relationships.add(
            Relationship(
                tenant_id=world.tenant_id,
                participant_id=world.participant_id,
                actor_id="mentor-1",
                relationship_type=RelationshipType.MENTOR,
            )
        )
        await session.commit()
    assert (await client.get(url, headers=headers)).status_code == 200


async def test_admin_api_creates_resources_within_actor_tenant(client: httpx.AsyncClient) -> None:
    platform = {"X-Cairn-Actor": "root", "X-Cairn-Roles": "platform_admin"}
    tenant = (await client.post("/v1/tenants", json={"name": "New Co"}, headers=platform)).json()
    admin = {
        "X-Cairn-Actor": "admin",
        "X-Cairn-Tenant": tenant["id"],
        "X-Cairn-Roles": "tenant_admin",
    }
    participant = await client.post(
        "/v1/participants",
        headers=admin,
        json={"display_name": "Synthetic P", "is_synthetic": True},
    )
    assert participant.status_code == 201
    journey = await client.post(
        "/v1/journeys",
        headers=admin,
        json={
            "participant_id": participant.json()["id"],
            "domain_pack": "demo",
            "title": "Reading",
        },
    )
    assert journey.status_code == 201
    assert journey.json()["domain_pack_version"] == "1.0.0"
    # Tenant admins cannot create tenants.
    assert (await client.post("/v1/tenants", json={"name": "x"}, headers=admin)).status_code == 403
