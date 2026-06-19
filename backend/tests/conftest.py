"""Test fixtures.

Phase 0 keeps these minimal and hermetic: an in-memory SQLite engine (so no remote
Postgres is touched) holding only the SQLite-compatible tables needed by the tests,
plus an httpx AsyncClient wired to the app with get_db overridden. The richer
as_role / auth_headers fixtures arrive with auth in Phase 1.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.models.campaign import Campaign
from app.models.user import User
from app.models.writing_skill import WritingSkill

# Tables that create cleanly on SQLite (no ARRAY/JSONB columns).
_SQLITE_TABLES = [User.__table__, WritingSkill.__table__, Campaign.__table__]


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        for table in _SQLITE_TABLES:
            await conn.run_sync(table.create)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient]:
    from app.db.session import get_db
    from app.main import app

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
