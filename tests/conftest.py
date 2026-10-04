"""Shared fixtures.

Unit tests run the real ORM against in-memory SQLite, the MockAIProvider, the
template renderer, no-op guardrails, in-memory context and inline workflows - no
network, no Docker, no API keys.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
import pytest

# Guarantee no test can pick up real credentials from the developer's shell.
os.environ.pop("CAIRN_OPENAI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

from cairn.api.app import create_app
from cairn.config.settings import (
    AIProviderKind,
    CairnSettings,
    ContextProviderKind,
    Environment,
    EvidenceStoreKind,
    GuardrailProviderKind,
    RendererKind,
    WorkflowDispatcherKind,
    get_settings,
)
from cairn.container import Container, build_container
from cairn.context.in_memory import InMemoryContextProvider
from cairn.domain.enums import ConsentScope, JourneyStatus
from cairn.domain.models import Consent, Journey, Participant, Tenant
from cairn.domain_packs.pack import DomainPack
from cairn.domain_packs.registry import DomainPackRegistry
from cairn.persistence.base import Base
from cairn.persistence.repositories import Repositories

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def registry() -> DomainPackRegistry:
    return DomainPackRegistry.from_directory(REPO_ROOT / "domain_packs")


@pytest.fixture
def parkinsons(registry: DomainPackRegistry) -> DomainPack:
    return registry.get("parkinsons")


@pytest.fixture
def mentorship(registry: DomainPackRegistry) -> DomainPack:
    return registry.get("mentorship")


@pytest.fixture
def demo(registry: DomainPackRegistry) -> DomainPack:
    return registry.get("demo")


@pytest.fixture
def settings(tmp_path: Path) -> CairnSettings:
    get_settings.cache_clear()
    return CairnSettings(
        _env_file=None,  # type: ignore[call-arg]
        env=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        # Pin every provider so CAIRN_* variables (e.g. in the Dev Container) cannot leak in.
        ai_provider=AIProviderKind.MOCK,
        renderer=RendererKind.TEMPLATE,
        context_provider=ContextProviderKind.IN_MEMORY,
        guardrail_provider=GuardrailProviderKind.NOOP,
        evidence_store=EvidenceStoreKind.LOCAL,
        workflow_dispatcher=WorkflowDispatcherKind.INLINE,
        local_evidence_path=tmp_path / "evidence",
        log_json=False,
        log_level="WARNING",
    )


@pytest.fixture
async def container(settings: CairnSettings) -> AsyncIterator[Container]:
    c = build_container(settings, context=InMemoryContextProvider())
    async with c.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield c
    await c.aclose()


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container=container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@dataclass(frozen=True)
class World:
    tenant_id: UUID
    participant_id: UUID
    journey_id: UUID

    def participant_headers(self) -> dict[str, str]:
        return {
            "X-Cairn-Actor": f"participant:{self.participant_id}",
            "X-Cairn-Tenant": str(self.tenant_id),
            "X-Cairn-Roles": "participant",
            "X-Cairn-Participant": str(self.participant_id),
        }

    def admin_headers(self) -> dict[str, str]:
        return {
            "X-Cairn-Actor": "admin@test",
            "X-Cairn-Tenant": str(self.tenant_id),
            "X-Cairn-Roles": "tenant_admin",
        }


async def make_world(
    container: Container,
    pack_id: str,
    *,
    tenant_name: str = "Tenant A",
    consents: list[ConsentScope] | None = None,
) -> World:
    pack = container.packs.get(pack_id)
    async with container.sessionmaker() as session:
        repos = Repositories(session)
        tenant = await repos.tenants.add(Tenant(name=tenant_name))
        participant = await repos.participants.add(
            Participant(
                tenant_id=tenant.id, display_name="Synthetic participant", is_synthetic=True
            )
        )
        journey = await repos.journeys.add(
            Journey(
                tenant_id=tenant.id,
                participant_id=participant.id,
                title=f"{pack_id} journey",
                domain_pack=pack.id,
                domain_pack_version=pack.version,
                status=JourneyStatus.ACTIVE,
                is_synthetic=True,
            )
        )
        for scope in consents if consents is not None else list(ConsentScope):
            await repos.consents.add(
                Consent(
                    tenant_id=tenant.id,
                    participant_id=participant.id,
                    journey_id=journey.id,
                    scope=scope,
                )
            )
        await session.commit()
    return World(tenant.id, participant.id, journey.id)


@pytest.fixture
def world_factory(container: Container):  # type: ignore[no-untyped-def]
    async def _make(pack_id: str, **kwargs):  # type: ignore[no-untyped-def]
        return await make_world(container, pack_id, **kwargs)

    return _make
