"""API tests for campaign CRUD, role gating by type, plan/generate/launch."""

import pytest

pytestmark = pytest.mark.asyncio

# Amplify needs both a target URL and the post text (it acts on a specific post
# and writes comments from that text), so every amplify payload carries both.
_SEED_URL = "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"


def amplify(title: str = "A") -> dict:
    return {
        "title": title,
        "type": "amplify",
        "seed_url": _SEED_URL,
        "seed_content": "x",
    }


async def test_viewer_can_create_amplify(client, as_role):
    async with as_role("viewer"):
        resp = await client.post("/v1/campaigns", json=amplify("Amplify launch"))
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "amplify"
    assert body["seed_urn"] == "urn:li:activity:7123456789012345678"
    assert body["status"] == "draft"


async def test_create_amplify_requires_url_and_text(client, as_role):
    async with as_role("viewer"):
        no_url = await client.post(
            "/v1/campaigns",
            json={"title": "A", "type": "amplify", "seed_content": "x"},
        )
        no_text = await client.post(
            "/v1/campaigns",
            json={"title": "A", "type": "amplify", "seed_url": _SEED_URL},
        )
    assert no_url.status_code == 422
    assert no_text.status_code == 422


async def test_create_distribute_requires_seed_text(client, as_role):
    async with as_role("editor"):
        resp = await client.post(
            "/v1/campaigns",
            json={"title": "D", "type": "distribute"},
        )
    assert resp.status_code == 422


async def test_viewer_cannot_create_distribute(client, as_role):
    async with as_role("viewer"):
        resp = await client.post(
            "/v1/campaigns",
            json={"title": "Dist", "type": "distribute", "seed_content": "seed"},
        )
    assert resp.status_code == 403


async def test_editor_can_create_distribute(client, as_role):
    async with as_role("editor"):
        resp = await client.post(
            "/v1/campaigns",
            json={"title": "Dist", "type": "distribute", "seed_content": "seed"},
        )
    assert resp.status_code == 201
    assert resp.json()["type"] == "distribute"


async def test_get_campaign_includes_counts(client, as_role):
    async with as_role("viewer") as user:
        created = await client.post(
            "/v1/campaigns",
            json=amplify(),
        )
        cid = created.json()["id"]
        # One amplify participant expands to like + comment + repost on the seed.
        await client.post(
            f"/v1/campaigns/{cid}/plan",
            json={"participant_ids": [str(user.id)]},
        )
        detail = await client.get(f"/v1/campaigns/{cid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["post_count"] == 3
    assert body["counts"].get("pending") == 3


async def test_generate_enqueues_and_sets_generating(client, as_role, enqueued):
    async with as_role("viewer") as user:
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]
        resp = await client.post(
            f"/v1/campaigns/{cid}/generate",
            json={"participant_ids": [str(user.id)]},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "generating"
    assert any(name == "generate_drafts" for name, _, _ in enqueued)


async def test_launch_requires_review_and_enqueues(client, as_role, enqueued):
    async with as_role("viewer") as user:
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]
        # Cannot launch from draft.
        early = await client.post(f"/v1/campaigns/{cid}/launch")
        assert early.status_code == 409

        await client.post(
            f"/v1/campaigns/{cid}/plan",
            json={"participant_ids": [str(user.id)]},
        )
        launched = await client.post(f"/v1/campaigns/{cid}/launch")
    assert launched.status_code == 200
    assert launched.json()["launched_by"] == str(user.id)
    assert any(name == "launch_campaign" for name, _, _ in enqueued)


async def test_patch_campaign_non_creator_forbidden(client, as_role):
    async with as_role("editor"):
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]
    async with as_role("editor", email="other@test.local"):
        resp = await client.patch(f"/v1/campaigns/{cid}", json={"title": "Hijack"})
    assert resp.status_code == 403


async def test_patch_campaign_creator_updates_and_reparses_seed(client, as_role):
    async with as_role("viewer"):
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]
        resp = await client.patch(
            f"/v1/campaigns/{cid}",
            json={
                "title": "Renamed",
                "seed_url": (
                    "https://www.linkedin.com/feed/update/"
                    "urn:li:activity:7000000000000000001/"
                ),
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Renamed"
    assert body["seed_urn"] == "urn:li:activity:7000000000000000001"


async def test_patch_campaign_with_media_writes_json_safe_audit(client, as_role, db):
    # image_asset_id is a UUID; the audit detail is JSONB, so the update must not
    # try to json-encode a raw UUID (regression: 500 on save).
    from app.models.asset import Asset

    async with as_role("editor") as user:  # noqa: F841
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]
        asset = Asset(content_type="image/png", size_bytes=3, data=b"abc")
        db.add(asset)
        await db.commit()
        resp = await client.patch(
            f"/v1/campaigns/{cid}",
            json={"image_asset_id": str(asset.id)},
        )
    assert resp.status_code == 200
    assert resp.json()["image_asset_id"] == str(asset.id)


async def test_patch_campaign_blocked_after_launch(client, as_role, db):
    from app.models.campaign import Campaign

    async with as_role("viewer"):
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]

        import uuid as _uuid

        campaign = await db.get(Campaign, _uuid.UUID(cid))
        campaign.status = "publishing"
        await db.commit()

        resp = await client.patch(f"/v1/campaigns/{cid}", json={"title": "Late"})
    assert resp.status_code == 409


async def test_plan_requires_creator_or_admin(client, as_role):
    async with as_role("editor") as owner:
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]
    async with as_role("viewer", email="intruder@test.local"):
        resp = await client.post(
            f"/v1/campaigns/{cid}/plan",
            json={"participant_ids": [str(owner.id)]},
        )
    assert resp.status_code == 403


async def test_viewer_cannot_plan_distribute(client, as_role):
    """A distribute campaign created by an editor stays editor-gated on plan."""
    async with as_role("editor"):
        created = await client.post(
            "/v1/campaigns",
            json={"title": "D", "type": "distribute", "seed_content": "x"},
        )
        cid = created.json()["id"]
    async with as_role("viewer", email="v@test.local") as viewer:
        resp = await client.post(
            f"/v1/campaigns/{cid}/plan",
            json={"participant_ids": [str(viewer.id)]},
        )
    # Either type-gate or creator-gate denies; both are 403.
    assert resp.status_code == 403


async def test_delete_campaign_removes_posts_and_audits(client, as_role, db):
    from sqlalchemy import func, select

    from app.models.audit_log import AuditLog
    from app.models.post import Post

    async with as_role("editor") as user:
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]
        await client.post(
            f"/v1/campaigns/{cid}/plan",
            json={"participant_ids": [str(user.id)]},
        )
        resp = await client.delete(f"/v1/campaigns/{cid}")
        assert resp.status_code == 204

        # Detail is gone, and no posts or campaign-scoped audit rows remain.
        gone = await client.get(f"/v1/campaigns/{cid}")
        assert gone.status_code == 404

    import uuid as _uuid

    cuid = _uuid.UUID(cid)
    posts = await db.scalar(
        select(func.count()).select_from(Post).where(Post.campaign_id == cuid)
    )
    audits = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.campaign_id == cuid)
    )
    assert posts == 0
    assert audits == 0
    # A terminal campaign_deleted audit row is written with a null campaign_id.
    deleted_rows = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "campaign_deleted")
    )
    assert deleted_rows >= 1


async def test_delete_campaign_non_owner_forbidden(client, as_role):
    async with as_role("editor"):
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]
    async with as_role("editor", email="intruder@test.local"):
        resp = await client.delete(f"/v1/campaigns/{cid}")
    assert resp.status_code == 403


async def test_delete_campaign_blocked_after_launch(client, as_role, db, monkeypatch):
    from app.config import settings
    from app.models.campaign import Campaign

    # Production protects launched campaigns from deletion.
    monkeypatch.setattr(settings, "ENV", "production")
    async with as_role("editor"):
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]

        import uuid as _uuid

        campaign = await db.get(Campaign, _uuid.UUID(cid))
        campaign.status = "publishing"
        await db.commit()

        resp = await client.delete(f"/v1/campaigns/{cid}")
    assert resp.status_code == 409


async def test_delete_campaign_after_launch_allowed_in_local(
    client, as_role, db, monkeypatch
):
    from app.config import settings
    from app.models.campaign import Campaign

    # Local/dev relaxes the rule so test campaigns in any state can be cleaned up.
    monkeypatch.setattr(settings, "ENV", "local")
    async with as_role("editor"):
        created = await client.post("/v1/campaigns", json=amplify())
        cid = created.json()["id"]

        import uuid as _uuid

        campaign = await db.get(Campaign, _uuid.UUID(cid))
        campaign.status = "completed"
        await db.commit()

        resp = await client.delete(f"/v1/campaigns/{cid}")
    assert resp.status_code == 204


async def test_list_only_shows_own_campaigns(client, as_role):
    async with as_role("editor"):
        await client.post("/v1/campaigns", json=amplify("mine"))
    async with as_role("viewer", email="other@test.local"):
        page = await client.get("/v1/campaigns")
    assert page.status_code == 200
    assert page.json()["items"] == []
