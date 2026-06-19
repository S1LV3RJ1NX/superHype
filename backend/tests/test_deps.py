"""Tests for core/deps.py: require_role admits and rejects correctly."""

from httpx import AsyncClient


async def test_require_role_admits_admin(client: AsyncClient, as_role):
    async with as_role("admin") as _admin:
        resp = await client.get("/v1/users")
    assert resp.status_code == 200


async def test_require_role_rejects_viewer(client: AsyncClient, as_role):
    async with as_role("viewer") as _viewer:
        resp = await client.get("/v1/users")
    assert resp.status_code == 403


async def test_require_role_rejects_editor(client: AsyncClient, as_role):
    async with as_role("editor") as _editor:
        resp = await client.get("/v1/users")
    assert resp.status_code == 403


async def test_unauthenticated_returns_401(client: AsyncClient):
    resp = await client.get("/v1/users/me")
    assert resp.status_code in (401, 403)
