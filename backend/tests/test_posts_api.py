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


async def _amplify_with_post(client, user, *, action="comment"):
    created = await client.post(
        "/v1/campaigns",
        json={
            "title": "A",
            "type": "amplify",
            "seed_url": (
                "https://www.linkedin.com/feed/update/"
                "urn:li:activity:7123456789012345678/"
            ),
            "seed_content": "x",
        },
    )
    cid = created.json()["id"]
    await client.post(
        f"/v1/campaigns/{cid}/plan",
        json={
            "assignments": [{"user_id": str(user.id), "action": action, "body": "hi"}]
        },
    )
    posts = await client.get(f"/v1/campaigns/{cid}/posts")
    return cid, posts.json()["items"][0]


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
    assert body["pending_count"] == 1


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


async def test_readiness_assisted_only_needs_no_linkedin(client, as_role):
    # Assisted-manual comments and likes are done by hand, so they need no token
    # and never trigger a reconnect prompt even without an account.
    async with as_role("editor") as user:
        cid, _ = await _amplify_with_post(client, user, action="comment")
        resp = await client.get(f"/v1/campaigns/{cid}/approval-readiness")
    body = resp.json()
    assert body["requires_linkedin"] is False
    assert body["needs_reconnect"] is False


async def test_missing_post_404(client, as_role):
    async with as_role("editor"):
        resp = await client.post(f"/v1/posts/{uuid.uuid4()}/approve")
    assert resp.status_code == 404
