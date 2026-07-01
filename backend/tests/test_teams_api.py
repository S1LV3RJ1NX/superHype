"""Tests for teams: CRUD RBAC, active-only listing, and self-service team set."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.team import Team
from app.models.user import User


async def _make_team(engine, name: str, *, is_active: bool = True) -> Team:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    team = Team(id=uuid.uuid4(), name=name, is_active=is_active)
    async with maker() as session:
        session.add(team)
        await session.commit()
    return team


async def test_list_teams_any_authed(client: AsyncClient, as_role, engine):
    await _make_team(engine, "Engineering")
    async with as_role("viewer"):
        resp = await client.get("/v1/teams")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()["items"]]
    assert "Engineering" in names


async def test_list_teams_excludes_archived(client: AsyncClient, as_role, engine):
    await _make_team(engine, "Active Team")
    await _make_team(engine, "Archived Team", is_active=False)
    async with as_role("viewer"):
        resp = await client.get("/v1/teams")
    names = [t["name"] for t in resp.json()["items"]]
    assert "Active Team" in names
    assert "Archived Team" not in names


async def test_non_admin_403_on_create(client: AsyncClient, as_role):
    async with as_role("editor"):
        resp = await client.post("/v1/teams", json={"name": "GTM"})
    assert resp.status_code == 403


async def test_non_admin_403_on_list_all(client: AsyncClient, as_role):
    async with as_role("editor"):
        resp = await client.get("/v1/teams/all")
    assert resp.status_code == 403


async def test_non_admin_403_on_patch(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Marketing")
    async with as_role("editor"):
        resp = await client.patch(f"/v1/teams/{team.id}", json={"name": "Sales"})
    assert resp.status_code == 403


async def test_admin_can_create_team(client: AsyncClient, as_role):
    async with as_role("admin"):
        resp = await client.post("/v1/teams", json={"name": "Founders"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Founders"
    assert body["is_active"] is True


async def test_create_duplicate_name_409(client: AsyncClient, as_role, engine):
    await _make_team(engine, "Founders")
    async with as_role("admin"):
        resp = await client.post("/v1/teams", json={"name": "Founders"})
    assert resp.status_code == 409


async def test_admin_can_rename_team(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Old Name")
    async with as_role("admin"):
        resp = await client.patch(f"/v1/teams/{team.id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


async def test_admin_can_archive_team(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Temp Team")
    async with as_role("admin"):
        resp = await client.patch(f"/v1/teams/{team.id}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        # Archived teams drop out of the public list but stay in the admin /all view.
        active = await client.get("/v1/teams")
        every = await client.get("/v1/teams/all")
    assert "Temp Team" not in [t["name"] for t in active.json()["items"]]
    assert "Temp Team" in [t["name"] for t in every.json()["items"]]


async def test_rename_to_existing_name_409(client: AsyncClient, as_role, engine):
    await _make_team(engine, "Engineering")
    team = await _make_team(engine, "Design")
    async with as_role("admin"):
        resp = await client.patch(f"/v1/teams/{team.id}", json={"name": "Engineering"})
    assert resp.status_code == 409


async def test_create_team_writes_audit(client: AsyncClient, as_role, engine):
    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    async with as_role("admin"):
        resp = await client.post("/v1/teams", json={"name": "Audited Team"})
    assert resp.status_code == 201

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        rows = await session.execute(
            select(AuditLog).where(AuditLog.action == "team_created")
        )
    logs = list(rows.scalars().all())
    assert any(log.detail.get("name") == "Audited Team" for log in logs)


async def test_member_count_reflects_assignment(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Counted Team")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            User(
                id=uuid.uuid4(),
                email="member@test.local",
                role="viewer",
                is_active=True,
                team_id=team.id,
            )
        )
        await session.commit()

    async with as_role("admin"):
        resp = await client.get("/v1/teams")
    counted = next(t for t in resp.json()["items"] if t["name"] == "Counted Team")
    assert counted["member_count"] == 1
