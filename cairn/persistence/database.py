"""Async engine and session management."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def create_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    if url.startswith("sqlite"):
        # In-memory SQLite (tests) must share one connection across sessions.
        return create_async_engine(
            url, echo=echo, poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    return create_async_engine(url, echo=echo, pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
