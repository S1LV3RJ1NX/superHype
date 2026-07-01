"""API tests for per-post actions: edit, approve, skip, and ownership gating."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.crypto import encrypt
from app.models.social_account import SocialAccount

pytestmark = pytest.mark.asyncio


async def _connect(db, user_id, *, status="active", expires_in_days=60):
    """Give a user a LinkedIn connection so approve can pass the reconnect gate."""
    acct = SocialAccount(
        user_id=user_id,
        platform="linkedin",
        external_urn="urn:li:person:test",
        display_name="Tester",
        access_token_enc=encrypt("tok"),
        refresh_token_enc=None,
        scopes=["w_member_social"],
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
        status=status,
    )
    db.add(acct)
    await db.commit()
    return acct


def _amplify_payload() -> dict:
    return {
        "title": "A",
        "type": "amplify",
        "seed_url": (
            "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"
        ),
        "seed_content": "x",
    }


async def _amplify_with_post(client, user, *, action="comment"):
    created = await client.post("/v1/campaigns", json=_amplify_payload())
    cid = created.json()["id"]
    # One amplify participant expands to like + comment + repost on the seed; the
    # caller picks which of those actions it wants to exercise.
    await client.post(
        f"/v1/campaigns/{cid}/plan",
        json={"participant_ids": [str(user.id)]},
    )
    posts = await client.get(f"/v1/campaigns/{cid}/posts")
    post = next(p for p in posts.json()["items"] if p["action"] == action)
    return cid, post


async def _launch(client, cid):
    """Launch a campaign so its posts can be approved (launch is compulsory)."""
    resp = await client.post(f"/v1/campaigns/{cid}/launch")
    assert resp.status_code == 200


async def test_cannot_approve_before_launch(client, as_role, db):
    # Launch is compulsory: pre-launch only edits to the plan are allowed.
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        await _connect(db, user.id)
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 409
    assert "Launch" in resp.json()["detail"]


async def test_owner_can_edit_then_approve(client, as_role, enqueued, db):
    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user)
        await _connect(db, user.id)
        edited = await client.patch(f"/v1/posts/{post['id']}", json={"body": "edited"})
        assert edited.status_code == 200
        assert edited.json()["body"] == "edited"

        await _launch(client, cid)
        approved = await client.post(f"/v1/posts/{post['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert any(name == "publish_post" for name, _, _ in enqueued)


async def test_approve_requires_reconnect_without_account(client, as_role):
    # A reshare publishes under the owner's token, so the reconnect gate applies
    # (unlike an assisted comment or like, which needs no token).
    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user, action="repost_comment")
        await _launch(client, cid)
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "linkedin_reconnect_required"


async def test_approve_requires_reconnect_when_stale(client, as_role, db):
    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user, action="repost_comment")
        await _connect(db, user.id, status="stale")
        await _launch(client, cid)
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "linkedin_reconnect_required"


async def test_non_owner_cannot_approve(client, as_role):
    async with as_role("editor") as owner:
        _, post = await _amplify_with_post(client, owner)
    async with as_role("editor", email="intruder@test.local"):
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 403


async def test_admin_cannot_approve_others_post(client, as_role, db):
    # Approval publishes under the owner's own token, so even an admin must not
    # approve on someone else's behalf.
    async with as_role("editor") as owner:
        _, post = await _amplify_with_post(client, owner)
        await _connect(db, owner.id)
    async with as_role("admin", email="boss@test.local"):
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 403


async def test_admin_can_skip_others_post(client, as_role):
    # Admin keeps the override on skip so a stuck or abandoned item can be cleared.
    async with as_role("editor") as owner:
        _, post = await _amplify_with_post(client, owner)
    async with as_role("admin", email="boss@test.local"):
        resp = await client.post(f"/v1/posts/{post['id']}/skip")
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


async def test_skip_marks_skipped(client, as_role):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        resp = await client.post(f"/v1/posts/{post['id']}/skip")
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


async def test_cannot_approve_already_approved(client, as_role, db):
    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user)
        await _connect(db, user.id)
        await _launch(client, cid)
        await client.post(f"/v1/posts/{post['id']}/approve")
        again = await client.post(f"/v1/posts/{post['id']}/approve")
    assert again.status_code == 409


async def test_assisted_comment_approve_needs_no_account(client, as_role, enqueued):
    # With Community Management API disabled (default), a comment is assisted-
    # manual: approval needs no LinkedIn token and just enqueues the worker.
    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user, action="comment")
        await _launch(client, cid)
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert any(name == "publish_post" for name, _, _ in enqueued)


async def test_owner_acknowledges_assisted_action(client, as_role, db):
    from app.models.post import Post

    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user, action="comment")
        await _launch(client, cid)
        await client.post(f"/v1/posts/{post['id']}/approve")
        # Stand in for the worker raising the assisted ask.
        pobj = await db.get(Post, uuid.UUID(post["id"]))
        pobj.status = "action_required"
        pobj.engagement_url = "https://www.linkedin.com/feed/update/urn:li:activity:1/"
        await db.commit()
        resp = await client.post(f"/v1/posts/{post['id']}/ack")
    assert resp.status_code == 200
    assert resp.json()["status"] == "acknowledged"
    assert resp.json()["acknowledged_at"] is not None


async def test_admin_cannot_acknowledge_others_action(client, as_role, db):
    # Only the person who was asked can mark it done; an admin cannot, since only
    # that person can actually perform the comment or like.
    from app.models.post import Post

    async with as_role("editor") as owner:
        cid, post = await _amplify_with_post(client, owner, action="comment")
        await _launch(client, cid)
        await client.post(f"/v1/posts/{post['id']}/approve")
        pobj = await db.get(Post, uuid.UUID(post["id"]))
        pobj.status = "action_required"
        await db.commit()
    async with as_role("admin", email="boss@test.local"):
        resp = await client.post(f"/v1/posts/{post['id']}/ack")
    assert resp.status_code == 403


async def test_ack_requires_action_required_status(client, as_role):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user, action="comment")
        resp = await client.post(f"/v1/posts/{post['id']}/ack")
    assert resp.status_code == 409


async def test_skip_from_action_required(client, as_role, db):
    from app.models.post import Post

    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user, action="comment")
        await _launch(client, cid)
        await client.post(f"/v1/posts/{post['id']}/approve")
        pobj = await db.get(Post, uuid.UUID(post["id"]))
        pobj.status = "action_required"
        await db.commit()
        resp = await client.post(f"/v1/posts/{post['id']}/skip")
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


async def test_owner_retries_failed_post(client, as_role, enqueued, db):
    # After a stale-token failure the owner reconnects and retries: the post goes
    # back to approved, the error clears, and the worker is re-enqueued.
    from app.models.campaign import Campaign
    from app.models.post import Post

    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user, action="repost_comment")
        await _connect(db, user.id)
        await _launch(client, cid)
        # Stand in for the worker failing the post and settling the campaign.
        pobj = await db.get(Post, uuid.UUID(post["id"]))
        pobj.status = "failed"
        pobj.error = "LinkedIn token invalid (stale)."
        cobj = await db.get(Campaign, uuid.UUID(cid))
        cobj.status = "completed"
        await db.commit()

        resp = await client.post(f"/v1/posts/{post['id']}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        assert resp.json()["error"] is None
        # The completed campaign reopens so the worker can run again.
        cobj = await db.get(Campaign, uuid.UUID(cid))
        await db.refresh(cobj)
        assert cobj.status == "publishing"
    assert any(name == "publish_post" for name, _, _ in enqueued)


async def test_owner_skips_failed_post(client, as_role, db):
    from app.models.post import Post

    async with as_role("editor") as user:
        cid, post = await _amplify_with_post(client, user, action="repost_comment")
        await _connect(db, user.id)
        await _launch(client, cid)
        pobj = await db.get(Post, uuid.UUID(post["id"]))
        pobj.status = "failed"
        await db.commit()
        resp = await client.post(f"/v1/posts/{post['id']}/skip")
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


async def test_readiness_requires_connect_when_no_account(client, as_role):
    # A reshare publishes under the owner's token, so with no account the
    # pre-flight check asks the owner to connect before approving.
    async with as_role("editor") as user:
        cid, _ = await _amplify_with_post(client, user, action="repost_comment")
        resp = await client.get(f"/v1/campaigns/{cid}/approval-readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_linkedin"] is True
    assert body["connected"] is False
    assert body["needs_reconnect"] is True
    # One amplify participant expands to like + comment + repost.
    assert body["pending_count"] == 3


async def test_readiness_clear_with_healthy_account(client, as_role, db):
    async with as_role("editor") as user:
        cid, _ = await _amplify_with_post(client, user, action="repost_comment")
        await _connect(db, user.id)
        resp = await client.get(f"/v1/campaigns/{cid}/approval-readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_linkedin"] is True
    assert body["connected"] is True
    assert body["needs_reconnect"] is False


async def test_readiness_stale_account_needs_reconnect(client, as_role, db):
    async with as_role("editor") as user:
        cid, _ = await _amplify_with_post(client, user, action="repost_comment")
        await _connect(db, user.id, status="stale")
        resp = await client.get(f"/v1/campaigns/{cid}/approval-readiness")
    assert resp.json()["needs_reconnect"] is True


async def test_readiness_assisted_only_needs_no_linkedin(client, as_role, db):
    # Assisted-manual comments and likes are done by hand, so they need no token
    # and never trigger a reconnect prompt even without an account. The auto plan
    # always adds a non-assisted repost, so build the assisted-only case directly.
    import uuid as _uuid

    from app.models.post import Post

    async with as_role("editor") as user:
        created = await client.post("/v1/campaigns", json=_amplify_payload())
        cid = created.json()["id"]
        db.add(
            Post(
                campaign_id=_uuid.UUID(cid),
                user_id=user.id,
                action="comment",
                status="pending",
                idempotency_key="assisted-only",
            )
        )
        await db.commit()
        resp = await client.get(f"/v1/campaigns/{cid}/approval-readiness")
    body = resp.json()
    assert body["requires_linkedin"] is False
    assert body["needs_reconnect"] is False


async def test_missing_post_404(client, as_role):
    async with as_role("editor"):
        resp = await client.post(f"/v1/posts/{uuid.uuid4()}/approve")
    assert resp.status_code == 404


async def _amplify_like_comment(client, user):
    """An amplify campaign whose participant has an assisted like + comment pair."""
    created = await client.post("/v1/campaigns", json=_amplify_payload())
    cid = created.json()["id"]
    await client.post(
        f"/v1/campaigns/{cid}/plan",
        json={"participant_ids": [str(user.id)]},
    )
    items = (await client.get(f"/v1/campaigns/{cid}/posts")).json()["items"]
    like = next(p for p in items if p["action"] == "like")
    comment = next(p for p in items if p["action"] == "comment")
    return cid, like, comment


async def test_postout_exposes_assisted_flag(client, as_role, monkeypatch):
    # The combined card relies on this flag to know which rows to merge. With the
    # Community Management API off (default) comment/like are assisted; the
    # non-assisted repost is not. Flipping the flag makes every action automated.
    from app.config import settings

    async with as_role("editor") as user:
        created = await client.post("/v1/campaigns", json=_amplify_payload())
        cid = created.json()["id"]
        await client.post(
            f"/v1/campaigns/{cid}/plan",
            json={"participant_ids": [str(user.id)]},
        )
        items = (await client.get(f"/v1/campaigns/{cid}/posts")).json()["items"]
        assisted = {p["action"]: p["assisted"] for p in items}
        assert assisted["comment"] is True
        assert assisted["like"] is True
        assert assisted["repost_comment"] is False

        monkeypatch.setattr(settings, "COMMUNITY_MANAGEMENT_ENABLED", True)
        items = (await client.get(f"/v1/campaigns/{cid}/posts")).json()["items"]
        assert all(p["assisted"] is False for p in items)


async def test_batch_approve_enqueues_both(client, as_role, enqueued):
    # Assisted like + comment approve together, need no LinkedIn token, and each
    # enqueues its own publish_post so the worker raises both asks.
    async with as_role("editor") as user:
        cid, like, comment = await _amplify_like_comment(client, user)
        await _launch(client, cid)
        resp = await client.post(
            "/v1/posts/batch",
            json={"op": "approve", "post_ids": [comment["id"], like["id"]]},
        )
    assert resp.status_code == 200
    assert {p["status"] for p in resp.json()} == {"approved"}
    published = {
        args[0] for name, args, _ in enqueued if name == "publish_post" and args
    }
    assert like["id"] in published
    assert comment["id"] in published


async def test_batch_ack_settles_both_and_completes(client, as_role, db):
    from app.models.campaign import Campaign
    from app.models.post import Post

    async with as_role("editor") as user:
        cid, like, comment = await _amplify_like_comment(client, user)
        await _launch(client, cid)
        items = (await client.get(f"/v1/campaigns/{cid}/posts")).json()["items"]
        repost = next(p for p in items if p["action"] == "repost_comment")
        # Skip the non-assisted repost so the only remaining rows are the pair.
        await client.post(f"/v1/posts/{repost['id']}/skip")
        # Stand in for the worker: put the campaign in publishing and raise both
        # assisted asks, then acknowledge them together.
        cobj = await db.get(Campaign, uuid.UUID(cid))
        cobj.status = "publishing"
        for pid in (like["id"], comment["id"]):
            pobj = await db.get(Post, uuid.UUID(pid))
            pobj.status = "action_required"
        await db.commit()

        resp = await client.post(
            "/v1/posts/batch",
            json={"op": "ack", "post_ids": [comment["id"], like["id"]]},
        )
        assert resp.status_code == 200
        assert {p["status"] for p in resp.json()} == {"acknowledged"}
        camp = (await client.get(f"/v1/campaigns/{cid}")).json()
    assert camp["status"] == "completed"


async def test_batch_skip_skips_both(client, as_role):
    async with as_role("editor") as user:
        cid, like, comment = await _amplify_like_comment(client, user)
        resp = await client.post(
            "/v1/posts/batch",
            json={"op": "skip", "post_ids": [comment["id"], like["id"]]},
        )
    assert resp.status_code == 200
    assert {p["status"] for p in resp.json()} == {"skipped"}


async def test_batch_non_owner_forbidden(client, as_role):
    async with as_role("editor") as owner:
        _, like, comment = await _amplify_like_comment(client, owner)
    async with as_role("editor", email="intruder@test.local"):
        resp = await client.post(
            "/v1/posts/batch",
            json={"op": "ack", "post_ids": [comment["id"], like["id"]]},
        )
    assert resp.status_code == 403


async def test_batch_rejects_mixed_campaigns(client, as_role):
    async with as_role("editor") as user:
        _, like_a, _ = await _amplify_like_comment(client, user)
        _, _, comment_b = await _amplify_like_comment(client, user)
        resp = await client.post(
            "/v1/posts/batch",
            json={"op": "skip", "post_ids": [like_a["id"], comment_b["id"]]},
        )
    assert resp.status_code == 400


async def test_batch_ack_wrong_state_rejects_whole_batch(client, as_role):
    # Both rows are pending (never raised as asks), so ack is invalid and the
    # atomic batch rejects rather than partially settling.
    async with as_role("editor") as user:
        cid, like, comment = await _amplify_like_comment(client, user)
        await _launch(client, cid)
        resp = await client.post(
            "/v1/posts/batch",
            json={"op": "ack", "post_ids": [comment["id"], like["id"]]},
        )
    assert resp.status_code == 409
