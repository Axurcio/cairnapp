"""Bootstrap derived context-store indices: ``python -m cairn.context.bootstrap``.

Run once by the Compose ``migrate`` job, after the canonical Alembic migration and
before the API and worker start, so they never race to create the same indices.
Idempotent. There is no data to migrate: the projection is rebuilt from Postgres.
"""

from __future__ import annotations

import asyncio

from cairn.config.settings import get_settings
from cairn.container import build_context_provider
from cairn.observability.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(level="WARNING", json_output=settings.log_json)
    provider = build_context_provider(settings)
    try:
        await provider.initialize()
        print(f"context store ready: {provider.name}")
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
