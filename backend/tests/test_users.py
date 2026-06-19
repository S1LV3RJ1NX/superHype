"""Tests for the users API: role change, last-admin guard, RBAC, audit."""

import uuid

from httpx import AsyncClient

from app.models.audit_log import AuditLog
from app.models.social_account import SocialAccount
from app.models.user import User


async def test_non_admin_403_on_list(client: AsyncClient, as_role):
    async with as_role("viewer"):
        resp = await client.get("/v1/users")
    assert resp.status_code == 403


async def test_non_admin_403_on_patch(client: AsyncClient, as_role):
    async with as_role("viewer"):
        resp = await client.patch(f"/v1/users/{uuid.uuid4()}", json={"role": "admin"})
    assert resp.status_code == 403


async def test_admin_can_list_users(client: AsyncClient, as_role):
    async with as_role("admin"):
        resp = await client.get("/v1/users")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


async def test_admin_can_change_role(client: AsyncClient, as_role, engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    target = User(
        id=uuid.uuid4(),
        email="target@test.local",
        name="Target",
        role="viewer",
        is_active=True,
    )
    async with maker() as session:
        session.add(target)
        await session.commit()

    async with as_role("admin"):
        resp = await client.patch(f"/v1/users/{target.id}", json={"role": "editor"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


async def test_role_change_writes_audit(client: AsyncClient, as_role, engine):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    target = User(
        id=uuid.uuid4(),
        email="audited@test.local",
        name="Audited",
        role="viewer",
        is_active=True,
    )
    async with maker() as session:
        session.add(target)
        await session.commit()

    async with as_role("admin"):
        resp = await client.patch(f"/v1/users/{target.id}", json={"role": "editor"})
    assert resp.status_code == 200

    async with maker() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.action == "role_change")
        )
        logs = list(result.scalars().all())
    assert len(logs) >= 1
    assert logs[0].detail["new_role"] == "editor"


async def test_last_admin_guard(client: AsyncClient, as_role, engine):
    async with as_role("admin") as admin_user:
        resp = await client.patch(f"/v1/users/{admin_user.id}", json={"role": "viewer"})
    assert resp.status_code == 409
    assert "last admin" in resp.json()["detail"].lower()


async def test_get_me(client: AsyncClient, as_role):
    async with as_role("viewer", email="me@test.local") as _user:
        resp = await client.get("/v1/users/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@test.local"


async def test_list_users_includes_linkedin_status(
    client: AsyncClient, as_role, engine
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    connected_user = User(
        id=uuid.uuid4(),
        email="connected@test.local",
        name="Connected",
        role="viewer",
        is_active=True,
    )
    async with maker() as session:
        session.add(connected_user)
        await session.commit()

        acct = SocialAccount(
            user_id=connected_user.id,
            platform="linkedin",
            external_urn="urn:li:person:abc",
            display_name="Connected",
            access_token_enc=b"enc",
            status="active",
        )
        session.add(acct)
        await session.commit()

    async with as_role("admin"):
        resp = await client.get("/v1/users")
    assert resp.status_code == 200
    items = resp.json()["items"]
    connected = [u for u in items if u["email"] == "connected@test.local"]
    assert len(connected) == 1
    assert connected[0]["linkedin_status"] == "active"


async def test_list_users_linkedin_status_none_for_unconnected(
    client: AsyncClient, as_role
):
    async with as_role("admin"):
        resp = await client.get("/v1/users")
    assert resp.status_code == 200
    items = resp.json()["items"]
    for u in items:
        if u.get("linkedin_status") is None:
            assert u["linkedin_status"] is None
            break
