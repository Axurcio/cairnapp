"""Website sign-in: accounts, browser sessions, CSRF and the journey listing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, update

from cairn.api.app import create_app
from cairn.auth.accounts import AccountError, create_account
from cairn.auth.context import Role
from cairn.auth.passwords import hash_password, verify_password
from cairn.config.settings import AuthProviderKind, CairnSettings, Environment
from cairn.container import Container
from cairn.domain.enums import JourneyStatus, RelationshipType
from cairn.domain.models import Journey, Participant, Relationship, utcnow
from cairn.persistence.models import AuditEventRow, LoginSessionRow, UserRow
from cairn.persistence.repositories import Repositories
from tests.conftest import World

PASSWORD = "correct horse battery"


async def add_account(
    container: Container,
    world: World,
    *,
    email: str,
    roles: set[Role],
    participant_id: UUID | None = None,
    actor_id: str | None = None,
) -> None:
    async with container.sessionmaker() as session:
        repos = Repositories(session)
        await create_account(
            repos,
            email=email,
            password=PASSWORD,
            display_name=email.split("@")[0],
            roles=roles,
            tenant_id=world.tenant_id,
            participant_id=participant_id,
            actor_id=actor_id,
        )
        await session.commit()


async def sign_in(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    csrf: str = response.json()["csrf_token"]
    return csrf


# ---------------------------------------------------------------- passwords


def test_password_hashes_are_salted_and_verifiable() -> None:
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second
    assert first.startswith("scrypt$")
    assert verify_password(PASSWORD, first)
    assert not verify_password("wrong password", first)
    assert not verify_password(PASSWORD, "not-a-hash")


# ---------------------------------------------------------------- login / session / logout


async def test_login_sets_httponly_session_cookie(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    await add_account(
        container,
        w,
        email="Ana@Example.org",
        roles={Role.PARTICIPANT},
        participant_id=w.participant_id,
    )

    response = await client.post(
        "/v1/auth/login", json={"email": "ana@example.org", "password": PASSWORD}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "cairn_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    body = response.json()
    assert body["account"]["roles"] == ["participant"]
    assert body["account"]["participant_id"] == str(w.participant_id)
    assert body["account"]["tenant_name"] == "Tenant A"
    assert "password_hash" not in body["account"]
    assert body["csrf_token"]

    # The session survives a page reload: the browser asks for it again.
    again = await client.get("/v1/auth/session")
    assert again.status_code == 200
    assert again.json()["csrf_token"] == body["csrf_token"]

    # Only a hash of the cookie token is stored.
    token = client.cookies["cairn_session"]
    async with container.sessionmaker() as session:
        stored = (await session.scalars(select(LoginSessionRow.token_hash))).all()
    assert stored
    assert token not in stored


async def test_wrong_password_and_unknown_email_look_the_same(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    await add_account(container, w, email="admin@example.org", roles={Role.TENANT_ADMIN})

    wrong = await client.post(
        "/v1/auth/login", json={"email": "admin@example.org", "password": "nope nope nope"}
    )
    unknown = await client.post(
        "/v1/auth/login", json={"email": "nobody@example.org", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers

    async with container.sessionmaker() as session:
        denied = (
            await session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.action == "session:login", AuditEventRow.outcome == "denied"
                )
            )
        ).all()
    assert len(denied) == 2


async def test_login_only_accepts_json_bodies(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    # Cross-site pages can send these content types without a CORS preflight, so login
    # must refuse them (login CSRF). This relies on FastAPI's strict content-type default.
    w: World = await world_factory("demo")
    await add_account(container, w, email="admin@example.org", roles={Role.TENANT_ADMIN})
    body = b'{"email": "admin@example.org", "password": "correct horse battery"}'
    for content_type in ("", "text/plain", "application/x-www-form-urlencoded"):
        response = await client.post(
            "/v1/auth/login", content=body, headers={"content-type": content_type}
        )
        assert response.status_code == 422, content_type
        assert "set-cookie" not in response.headers


async def test_inactive_accounts_cannot_sign_in(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    await add_account(container, w, email="gone@example.org", roles={Role.TENANT_ADMIN})
    async with container.sessionmaker() as session:
        await session.execute(update(UserRow).values(active=False))
        await session.commit()

    response = await client.post(
        "/v1/auth/login", json={"email": "gone@example.org", "password": PASSWORD}
    )
    assert response.status_code == 401


async def test_logout_revokes_the_session(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    await add_account(container, w, email="admin@example.org", roles={Role.TENANT_ADMIN})
    csrf = await sign_in(client, "admin@example.org")
    token = client.cookies["cairn_session"]

    assert (await client.post("/v1/auth/logout")).status_code == 403  # CSRF required
    assert (await client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})).status_code == 204

    # Replaying the old cookie no longer works.
    client.cookies.set("cairn_session", token)
    assert (await client.get("/v1/auth/session")).status_code == 401
    assert (await client.get("/v1/journeys")).status_code == 401


async def test_signing_in_again_revokes_the_previous_session(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    await add_account(container, w, email="admin@example.org", roles={Role.TENANT_ADMIN})
    await sign_in(client, "admin@example.org")
    first = client.cookies["cairn_session"]
    await sign_in(client, "admin@example.org")
    assert client.cookies["cairn_session"] != first

    client.cookies.set("cairn_session", first)
    assert (await client.get("/v1/auth/session")).status_code == 401


async def test_expired_sessions_are_rejected(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    await add_account(container, w, email="admin@example.org", roles={Role.TENANT_ADMIN})
    await sign_in(client, "admin@example.org")
    async with container.sessionmaker() as session:
        await session.execute(
            update(LoginSessionRow).values(expires_at=utcnow() - timedelta(seconds=1))
        )
        await session.commit()

    assert (await client.get("/v1/auth/session")).status_code == 401
    assert (await client.get(f"/v1/journeys/{w.journey_id}")).status_code == 401


# ---------------------------------------------------------------- using the app with a session


async def test_session_acts_as_the_account_and_writes_need_csrf(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    await add_account(
        container,
        w,
        email="ana@example.org",
        roles={Role.PARTICIPANT},
        participant_id=w.participant_id,
    )
    csrf = await sign_in(client, "ana@example.org")

    journeys = await client.get("/v1/journeys")
    assert journeys.status_code == 200
    assert [j["id"] for j in journeys.json()] == [str(w.journey_id)]
    assert journeys.json()[0]["participant_display_name"] == "Synthetic participant"

    message = {"text": "I finished the first chapter."}
    blocked = await client.post(f"/v1/journeys/{w.journey_id}/messages", json=message)
    assert blocked.status_code == 403
    assert "CSRF" in blocked.json()["detail"]

    forged = await client.post(
        f"/v1/journeys/{w.journey_id}/messages", json=message, headers={"X-CSRF-Token": "guess"}
    )
    assert forged.status_code == 403

    sent = await client.post(
        f"/v1/journeys/{w.journey_id}/messages", json=message, headers={"X-CSRF-Token": csrf}
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["response"]["text"]


async def test_session_cannot_reach_other_tenants(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    a: World = await world_factory("demo", tenant_name="Tenant A")
    b: World = await world_factory("demo", tenant_name="Tenant B")
    await add_account(container, a, email="admin@a.example", roles={Role.TENANT_ADMIN})
    await sign_in(client, "admin@a.example")

    assert (await client.get(f"/v1/journeys/{a.journey_id}")).status_code == 200
    assert (await client.get(f"/v1/journeys/{b.journey_id}")).status_code == 404
    listed = (await client.get("/v1/journeys")).json()
    assert [j["id"] for j in listed] == [str(a.journey_id)]


@pytest.fixture
async def session_only_client(
    settings: CairnSettings, container: Container
) -> AsyncIterator[httpx.AsyncClient]:
    container.settings = settings.model_copy(update={"auth_provider": AuthProviderKind.SESSION})
    app = create_app(container=container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_session_mode_turns_off_header_auth(
    session_only_client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    headers_only = await session_only_client.get(
        f"/v1/journeys/{w.journey_id}", headers=w.admin_headers()
    )
    assert headers_only.status_code == 401

    await add_account(container, w, email="admin@example.org", roles={Role.TENANT_ADMIN})
    await sign_in(session_only_client, "admin@example.org")
    assert (await session_only_client.get(f"/v1/journeys/{w.journey_id}")).status_code == 200


def test_production_requires_secure_session_cookies() -> None:
    with pytest.raises(ValueError, match="session_cookie_secure"):
        CairnSettings(
            _env_file=None,  # type: ignore[call-arg]
            env=Environment.PRODUCTION,
            auth_provider=AuthProviderKind.SESSION,
            database_url="postgresql+asyncpg://cairn:s3cret@db:5432/cairn",
        )


# ---------------------------------------------------------------- journey listing by role


async def test_journey_list_follows_relationships_and_ownership(
    client: httpx.AsyncClient, container: Container, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    pack = container.packs.get("demo")
    async with container.sessionmaker() as session:
        repos = Repositories(session)
        other = await repos.participants.add(
            Participant(tenant_id=w.tenant_id, display_name="Other participant", is_synthetic=True)
        )
        other_journey = await repos.journeys.add(
            Journey(
                tenant_id=w.tenant_id,
                participant_id=other.id,
                title="other journey",
                domain_pack=pack.id,
                domain_pack_version=pack.version,
                status=JourneyStatus.ACTIVE,
                is_synthetic=True,
            )
        )
        await repos.relationships.add(
            Relationship(
                tenant_id=w.tenant_id,
                participant_id=other.id,
                actor_id="mentor@test",
                relationship_type=RelationshipType.MENTOR,
            )
        )
        await session.commit()

    def ids(response: httpx.Response) -> set[str]:
        assert response.status_code == 200, response.text
        return {j["id"] for j in response.json()}

    mentor = {
        "X-Cairn-Actor": "mentor@test",
        "X-Cairn-Tenant": str(w.tenant_id),
        "X-Cairn-Roles": "facilitator",
    }
    stranger = {**mentor, "X-Cairn-Actor": "stranger@test"}

    assert ids(await client.get("/v1/journeys", headers=w.participant_headers())) == {
        str(w.journey_id)
    }
    assert ids(await client.get("/v1/journeys", headers=mentor)) == {str(other_journey.id)}
    assert ids(await client.get("/v1/journeys", headers=stranger)) == set()
    assert ids(await client.get("/v1/journeys", headers=w.admin_headers())) == {
        str(w.journey_id),
        str(other_journey.id),
    }


# ---------------------------------------------------------------- provisioning rules


async def test_account_provisioning_rules(container: Container, world_factory) -> None:  # type: ignore[no-untyped-def]
    a: World = await world_factory("demo", tenant_name="Tenant A")
    b: World = await world_factory("demo", tenant_name="Tenant B")

    async def attempt(**overrides: object) -> None:
        values: dict[str, object] = {
            "email": "x@example.org",
            "password": PASSWORD,
            "display_name": "X",
            "roles": {Role.PARTICIPANT},
            "tenant_id": a.tenant_id,
            "participant_id": a.participant_id,
        }
        values.update(overrides)
        async with container.sessionmaker() as session:
            await create_account(Repositories(session), **values)  # type: ignore[arg-type]
            await session.commit()

    with pytest.raises(AccountError, match="at least 12"):
        await attempt(password="short")
    with pytest.raises(AccountError, match="participant not found"):
        await attempt(participant_id=b.participant_id)  # another tenant's participant
    with pytest.raises(AccountError, match="need a participant"):
        await attempt(participant_id=None)
    with pytest.raises(AccountError, match="no tenant"):
        await attempt(roles={Role.TENANT_ADMIN}, tenant_id=None, participant_id=None)
    await attempt()
    with pytest.raises(AccountError, match="already exists"):
        await attempt(email="X@Example.org")


async def test_consents_endpoint_reflects_revocation(
    client: httpx.AsyncClient, world_factory
) -> None:  # type: ignore[no-untyped-def]
    w: World = await world_factory("demo")
    before = await client.get(
        f"/v1/journeys/{w.journey_id}/consents", headers=w.participant_headers()
    )
    assert before.status_code == 200
    assert "evidence" in before.json()["granted"]

    revoked = await client.post(
        f"/v1/journeys/{w.journey_id}/consent/revoke",
        json={"scopes": ["evidence"]},
        headers=w.participant_headers(),
    )
    assert revoked.status_code == 202
    after = await client.get(
        f"/v1/journeys/{w.journey_id}/consents", headers=w.participant_headers()
    )
    assert "evidence" not in after.json()["granted"]
    assert "conversation" in after.json()["granted"]
