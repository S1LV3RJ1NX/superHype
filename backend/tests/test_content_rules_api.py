"""API tests for the global content rules document (admin only)."""

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.content_rule import ContentRule
from app.repositories.content_rule_repo import content_rule_repo

pytestmark = pytest.mark.asyncio


async def test_repo_tolerates_duplicate_singleton_rows(db):
    # No DB constraint enforces the singleton, so a create race could leave two
    # rows. Reads must not raise MultipleResultsFound; the oldest wins.
    db.add(ContentRule(body="older"))
    await db.flush()
    db.add(ContentRule(body="newer"))
    await db.flush()

    assert await content_rule_repo.get_body(db) == "older"
    row = await content_rule_repo.set_body(db, "updated", actor_id=None)
    assert row.body == "updated"
    assert await content_rule_repo.get_body(db) == "updated"


async def test_admin_can_set_and_get_rules(client, as_role):
    async with as_role("admin"):
        put = await client.put(
            "/v1/content-rules", json={"body": "Always write in English."}
        )
        assert put.status_code == 200
        assert put.json()["body"] == "Always write in English."

        got = await client.get("/v1/content-rules")
        assert got.status_code == 200
        assert got.json()["body"] == "Always write in English."


async def test_get_with_no_rules_returns_empty(client, as_role):
    async with as_role("admin"):
        got = await client.get("/v1/content-rules")
    assert got.status_code == 200
    assert got.json()["body"] is None


async def test_non_admin_cannot_read_or_write(client, as_role):
    async with as_role("editor"):
        assert (await client.get("/v1/content-rules")).status_code == 403
        assert (
            await client.put("/v1/content-rules", json={"body": "x"})
        ).status_code == 403
    async with as_role("viewer"):
        assert (
            await client.put("/v1/content-rules", json={"body": "x"})
        ).status_code == 403


async def test_update_writes_audit(client, as_role, db):
    async with as_role("admin"):
        await client.put("/v1/content-rules", json={"body": "hello"})
    rows = (
        (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "content_rules_updated")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) >= 1
