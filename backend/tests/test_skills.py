"""Tests for writing-skill API endpoints."""

import pytest


@pytest.mark.asyncio
async def test_viewer_can_list_skills(client, as_role):
    async with as_role("viewer"):
        resp = await client.get("/v1/skills")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_create_skill(client, as_role):
    async with as_role("viewer"):
        resp = await client.post(
            "/v1/skills",
            json={"name": "Blocked", "instructions": "test"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_editor_can_create_skill_as_draft(client, as_role):
    async with as_role("editor"):
        resp = await client.post(
            "/v1/skills",
            json={"name": "My Skill", "instructions": "write posts"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Skill"
    assert data["is_default"] is False
    assert data["status"] == "draft"
    assert data["is_seed"] is False


@pytest.mark.asyncio
async def test_editor_can_update_non_seed_skill(client, as_role):
    async with as_role("editor") as _user:
        create_resp = await client.post(
            "/v1/skills",
            json={"name": "Original", "instructions": "v1"},
        )
        skill_id = create_resp.json()["id"]
        update_resp = await client.patch(
            f"/v1/skills/{skill_id}",
            json={"name": "Updated"},
        )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated"


@pytest.mark.asyncio
async def test_cannot_update_seed_skill(client, as_role, db):
    from app.models.writing_skill import WritingSkill

    seed = WritingSkill(
        name="Seed", instructions="locked", is_default=True, is_seed=True
    )
    db.add(seed)
    await db.commit()
    await db.refresh(seed)

    async with as_role("editor"):
        resp = await client.patch(
            f"/v1/skills/{seed.id}",
            json={"name": "Hacked"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cannot_archive_seed_skill(client, as_role, db):
    from app.models.writing_skill import WritingSkill

    seed = WritingSkill(name="Seed", instructions="locked", is_seed=True)
    db.add(seed)
    await db.commit()
    await db.refresh(seed)

    async with as_role("editor"):
        resp = await client.delete(f"/v1/skills/{seed.id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_publish_draft_skill(client, as_role):
    async with as_role("editor"):
        create_resp = await client.post(
            "/v1/skills",
            json={"name": "Draft Skill", "instructions": "draft"},
        )
        skill_id = create_resp.json()["id"]
        assert create_resp.json()["status"] == "draft"

        publish_resp = await client.post(f"/v1/skills/{skill_id}/publish")
    assert publish_resp.status_code == 200
    assert publish_resp.json()["status"] == "published"


@pytest.mark.asyncio
async def test_publish_already_published_returns_400(client, as_role):
    async with as_role("editor"):
        r = await client.post(
            "/v1/skills",
            json={"name": "Pub", "instructions": "i"},
        )
        skill_id = r.json()["id"]
        await client.post(f"/v1/skills/{skill_id}/publish")
        resp = await client.post(f"/v1/skills/{skill_id}/publish")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cannot_set_draft_as_default(client, as_role):
    async with as_role("editor"):
        r = await client.post(
            "/v1/skills",
            json={"name": "Draft", "instructions": "i"},
        )
        skill_id = r.json()["id"]
        resp = await client.post(f"/v1/skills/{skill_id}/set-default")
    assert resp.status_code == 400
    assert "draft" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_set_default_flips(client, as_role):
    async with as_role("editor") as _user:
        r1 = await client.post(
            "/v1/skills",
            json={"name": "First", "instructions": "i1"},
        )
        s1_id = r1.json()["id"]
        await client.post(f"/v1/skills/{s1_id}/publish")
        await client.post(f"/v1/skills/{s1_id}/set-default")

        r2 = await client.post(
            "/v1/skills",
            json={"name": "Second", "instructions": "i2"},
        )
        s2_id = r2.json()["id"]
        await client.post(f"/v1/skills/{s2_id}/publish")
        await client.post(f"/v1/skills/{s2_id}/set-default")

        resp1 = await client.get(f"/v1/skills/{s1_id}")
        resp2 = await client.get(f"/v1/skills/{s2_id}")

    assert resp1.json()["is_default"] is False
    assert resp2.json()["is_default"] is True


@pytest.mark.asyncio
async def test_archive_default_returns_409(client, as_role):
    async with as_role("editor") as _user:
        r = await client.post(
            "/v1/skills",
            json={"name": "Default", "instructions": "i"},
        )
        skill_id = r.json()["id"]
        await client.post(f"/v1/skills/{skill_id}/publish")
        await client.post(f"/v1/skills/{skill_id}/set-default")
        resp = await client.delete(f"/v1/skills/{skill_id}")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_archive_non_default_succeeds(client, as_role):
    async with as_role("editor") as _user:
        r = await client.post(
            "/v1/skills",
            json={"name": "Archivable", "instructions": "i"},
        )
        skill_id = r.json()["id"]
        resp = await client.delete(f"/v1/skills/{skill_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_skill_mutation_writes_audit(client, as_role, db):
    async with as_role("editor") as user:
        await client.post(
            "/v1/skills",
            json={"name": "Audited", "instructions": "test"},
        )

    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    result = await db.execute(
        select(AuditLog).where(
            AuditLog.actor_id == user.id,
            AuditLog.action == "skill_created",
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_publish_writes_audit(client, as_role, db):
    async with as_role("editor") as user:
        r = await client.post(
            "/v1/skills",
            json={"name": "To Publish", "instructions": "i"},
        )
        skill_id = r.json()["id"]
        await client.post(f"/v1/skills/{skill_id}/publish")

    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    result = await db.execute(
        select(AuditLog).where(
            AuditLog.actor_id == user.id,
            AuditLog.action == "skill_published",
        )
    )
    assert result.scalar_one_or_none() is not None
