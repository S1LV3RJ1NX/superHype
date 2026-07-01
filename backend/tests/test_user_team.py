"""Tests for self-service team selection and team fields on user responses."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.audit_log import AuditLog
from app.models.team import Team


async def _make_team(engine, name: str, *, is_active: bool = True) -> Team:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    team = Team(id=uuid.uuid4(), name=name, is_active=is_active)
    async with maker() as session:
        session.add(team)
        await session.commit()
    return team


async def test_new_user_has_no_team(client: AsyncClient, as_role):
    async with as_role("viewer", email="fresh@test.local"):
        resp = await client.get("/v1/users/me")
    assert resp.status_code == 200
    assert resp.json()["team_id"] is None


async def test_set_my_team(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "GTM")
    async with as_role("viewer"):
        resp = await client.patch("/v1/users/me", json={"team_id": str(team.id)})
        assert resp.status_code == 200
        assert resp.json()["team_id"] == str(team.id)
        assert resp.json()["team_name"] == "GTM"

        me = await client.get("/v1/users/me")
    assert me.json()["team_id"] == str(team.id)
    assert me.json()["team_name"] == "GTM"


async def test_set_my_team_rejects_unknown(client: AsyncClient, as_role):
    async with as_role("viewer"):
        resp = await client.patch("/v1/users/me", json={"team_id": str(uuid.uuid4())})
    assert resp.status_code == 404


async def test_set_my_team_rejects_archived(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Defunct", is_active=False)
    async with as_role("viewer"):
        resp = await client.patch("/v1/users/me", json={"team_id": str(team.id)})
    assert resp.status_code == 404


async def test_set_my_team_writes_audit(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Marketing and Sales")
    async with as_role("viewer") as user:
        resp = await client.patch("/v1/users/me", json={"team_id": str(team.id)})
        assert resp.status_code == 200
        actor_id = user.id

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        rows = await session.execute(
            select(AuditLog).where(AuditLog.action == "team_assigned")
        )
    logs = list(rows.scalars().all())
    assert any(log.actor_id == actor_id for log in logs)


async def test_editor_team_auto_grants_editor(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "GTM")
    async with as_role("viewer"):
        resp = await client.patch("/v1/users/me", json={"team_id": str(team.id)})
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


async def test_editor_team_auto_grant_writes_audit(
    client: AsyncClient, as_role, engine
):
    team = await _make_team(engine, "GTM")
    async with as_role("viewer") as user:
        resp = await client.patch("/v1/users/me", json={"team_id": str(team.id)})
        assert resp.status_code == 200
        actor_id = user.id

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        rows = await session.execute(
            select(AuditLog).where(AuditLog.action == "role_change")
        )
    logs = list(rows.scalars().all())
    grant = [
        log
        for log in logs
        if log.actor_id == actor_id and log.detail.get("reason") == "team_auto_grant"
    ]
    assert len(grant) == 1
    assert grant[0].detail["new_role"] == "editor"


async def test_non_editor_team_keeps_viewer(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Engineering")
    async with as_role("viewer"):
        resp = await client.patch("/v1/users/me", json={"team_id": str(team.id)})
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"


async def test_editor_team_never_demotes_admin(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Engineering")
    async with as_role("admin"):
        resp = await client.patch("/v1/users/me", json={"team_id": str(team.id)})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_roster_includes_team_id(client: AsyncClient, as_role, engine):
    team = await _make_team(engine, "Engineering")
    async with as_role("viewer") as user:
        await client.patch("/v1/users/me", json={"team_id": str(team.id)})
        resp = await client.get("/v1/users/roster?limit=100")
        mine = next(u for u in resp.json()["items"] if u["id"] == str(user.id))
    assert mine["team_id"] == str(team.id)
