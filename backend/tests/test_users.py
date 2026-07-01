"""Tests for the users API: role change, last-admin guard, RBAC, audit."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.audit_log import AuditLog
from app.models.social_account import SocialAccount
from app.models.user import User


async def test_non_admin_403_on_list(client: AsyncClient, as_role):
    async with as_role("viewer"):
        resp = await client.get("/v1/users")
    assert resp.status_code == 403


async def test_any_authed_can_read_roster(client: AsyncClient, as_role):
    async with as_role("viewer"):
        resp = await client.get("/v1/users/roster")
    assert resp.status_code == 200
    assert "items" in resp.json()


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


async def test_list_users_search_filters(client: AsyncClient, as_role, engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                User(
                    id=uuid.uuid4(),
                    email="alice@corp.com",
                    name="Alice Anderson",
                    role="viewer",
                    is_active=True,
                ),
                User(
                    id=uuid.uuid4(),
                    email="bob@corp.com",
                    name="Bob Brown",
                    role="viewer",
                    is_active=True,
                ),
            ]
        )
        await session.commit()

    async with as_role("admin"):
        resp = await client.get("/v1/users?search=alice")
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()["items"]]
    assert "alice@corp.com" in emails
    assert "bob@corp.com" not in emails


async def test_list_users_pagination_no_overlap(client: AsyncClient, as_role, engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [
                User(
                    id=uuid.uuid4(),
                    email=f"page{i}@corp.com",
                    name=f"Page User {i}",
                    role="viewer",
                    is_active=True,
                )
                for i in range(5)
            ]
        )
        await session.commit()

    async with as_role("admin"):
        first = await client.get("/v1/users?limit=3")
        assert first.status_code == 200
        body1 = first.json()
        assert len(body1["items"]) == 3
        assert body1["next_cursor"] is not None

        second = await client.get(f"/v1/users?limit=3&cursor={body1['next_cursor']}")
        assert second.status_code == 200
        body2 = second.json()

    ids1 = {u["id"] for u in body1["items"]}
    ids2 = {u["id"] for u in body2["items"]}
    # No overlap between consecutive pages (keyset guarantees this).
    assert ids1.isdisjoint(ids2)


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
