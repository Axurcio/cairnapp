"""Integration tests run against the Docker Compose services.

Enabled with ``CAIRN_INTEGRATION=1`` (``make integration`` sets it). Service
addresses come from the normal ``CAIRN_*`` settings, so the same tests run from
the host (localhost ports) or inside the Dev Container (service names).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from alembic import command
from alembic.config import Config

from cairn.api.app import create_app
from cairn.config.settings import CairnSettings
from cairn.container import Container, build_container
from cairn.context.in_memory import InMemoryContextProvider
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.integration


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("CAIRN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="set CAIRN_INTEGRATION=1 (make integration) to run")
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def pg_settings() -> CairnSettings:
    settings = CairnSettings()
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("integration tests need CAIRN_DATABASE_URL pointing at Postgres")
    return settings


@pytest.fixture(scope="session")
def migrated(pg_settings: CairnSettings) -> CairnSettings:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", pg_settings.database_url)
    command.upgrade(cfg, "head")
    return pg_settings


@pytest.fixture
async def pg_container(migrated: CairnSettings) -> AsyncIterator[Container]:
    """Real Postgres; in-memory context and inline workflows keep this test self-contained."""
    from cairn.config.settings import WorkflowDispatcherKind

    settings = migrated.model_copy(update={"workflow_dispatcher": WorkflowDispatcherKind.INLINE})
    container = build_container(settings, context=InMemoryContextProvider())
    yield container
    await container.aclose()


@pytest.fixture
async def pg_client(pg_container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container=pg_container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
