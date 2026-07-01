"""Test fixtures.

Hermetic in-memory SQLite engine (no remote Postgres required), httpx AsyncClient
wired to the app, and auth helpers: as_role overrides get_current_user with a
synthetic user of a given role, auth_headers mints a real JWT.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.models.asset import Asset
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.models.team import Team
from app.models.user import User

_SQLITE_TABLES = [
    # teams before users: users.team_id has a foreign key to teams.
    Team.__table__,
    User.__table__,
    Asset.__table__,
    Campaign.__table__,
    Post.__table__,
    AuditLog.__table__,
    SocialAccount.__table__,
]


@pytest.fixture(autouse=True)
def _pin_account_guardrails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin per-account action guardrails so the suite ignores local .env tuning.

    The publish-defer tests assert on exact min-gap spacing and the daily cap. A
    developer's backend/.env may relax these for fast local UI testing, so pin
    them to the code defaults here to keep tests deterministic.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "MIN_SECONDS_BETWEEN_ACCOUNT_ACTIONS", 90)
    monkeypatch.setattr(settings, "MAX_ACTIONS_PER_ACCOUNT_PER_DAY", 10)
    # Default to the self-serve world (assisted-manual comments and likes), so
    # the suite is deterministic regardless of a developer's local .env. Tests
    # that exercise the automated comment/like path opt in with the cm_enabled
    # fixture.
    monkeypatch.setattr(settings, "COMMUNITY_MANAGEMENT_ENABLED", False)


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


def _make_user(
    role: str = "viewer",
    email: str | None = None,
    user_id: uuid.UUID | None = None,
) -> User:
    return User(
        id=user_id or uuid.uuid4(),
        email=email or f"{role}@test.local",
        name=f"Test {role.title()}",
        role=role,
        is_active=True,
    )


@pytest_asyncio.fixture
def as_role(client: AsyncClient, engine: AsyncEngine):
    """Override get_current_user to inject a user of the given role.

    Returns a context manager that yields the synthetic user and injects it into
    the database so foreign-key-dependent queries work.
    """
    from contextlib import asynccontextmanager

    from app.core.deps import get_current_user
    from app.main import app

    @asynccontextmanager
    async def _override(
        role: str = "viewer",
        email: str | None = None,
        user_id: uuid.UUID | None = None,
    ):
        user = _make_user(role=role, email=email, user_id=user_id)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async with maker() as session:
            user = await session.merge(user)
            await session.commit()
            await session.refresh(user)

        async def _get_user() -> User:
            return user

        app.dependency_overrides[get_current_user] = _get_user
        try:
            yield user
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    return _override


@pytest_asyncio.fixture(autouse=True)
async def enqueued(monkeypatch):
    """Stub the ARQ enqueue so requests never reach Redis; records job calls."""
    import app.workers.queue as queue_mod

    calls: list[tuple] = []

    async def _enqueue(name: str, *args, **kwargs):
        calls.append((name, args, kwargs))
        return None

    monkeypatch.setattr(queue_mod, "enqueue_job", _enqueue)
    return calls


@pytest_asyncio.fixture
async def mock_redis():
    """Provide a fakeredis client and patch get_redis everywhere it is imported."""
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    import app.controllers.connection_controller as ctrl_mod
    import app.core.redis as redis_mod

    orig_core = redis_mod.get_redis
    orig_ctrl = ctrl_mod.get_redis

    async def _fake_get_redis():
        return fake

    redis_mod.get_redis = _fake_get_redis
    ctrl_mod.get_redis = _fake_get_redis
    try:
        yield fake
    finally:
        redis_mod.get_redis = orig_core
        ctrl_mod.get_redis = orig_ctrl
        await fake.aclose()


@pytest_asyncio.fixture
async def auth_headers() -> dict[str, str]:
    """Mint a real JWT for a synthetic user and return the Authorization header."""

    async def _headers(
        user_id: uuid.UUID | None = None,
        email: str = "test@test.local",
        role: str = "viewer",
    ) -> dict[str, str]:
        uid = user_id or uuid.uuid4()
        token = await create_access_token(user_id=uid, email=email, role=role)
        return {"Authorization": f"Bearer {token}"}

    return _headers  # type: ignore[return-value]
