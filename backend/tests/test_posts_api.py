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


async def _amplify_with_post(client, user):
    created = await client.post(
        "/v1/campaigns",
        json={"title": "A", "type": "amplify", "seed_content": "x"},
    )
    cid = created.json()["id"]
    await client.post(
        f"/v1/campaigns/{cid}/plan",
        json={
            "assignments": [
                {"user_id": str(user.id), "action": "comment", "body": "hi"}
            ]
        },
    )
    posts = await client.get(f"/v1/campaigns/{cid}/posts")
    return cid, posts.json()["items"][0]


async def test_owner_can_edit_then_approve(client, as_role, enqueued, db):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        await _connect(db, user.id)
        edited = await client.patch(f"/v1/posts/{post['id']}", json={"body": "edited"})
        assert edited.status_code == 200
        assert edited.json()["body"] == "edited"

        approved = await client.post(f"/v1/posts/{post['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert any(name == "publish_post" for name, _, _ in enqueued)


async def test_approve_requires_reconnect_without_account(client, as_role):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "linkedin_reconnect_required"


async def test_approve_requires_reconnect_when_stale(client, as_role, db):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        await _connect(db, user.id, status="stale")
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "linkedin_reconnect_required"


async def test_non_owner_cannot_approve(client, as_role):
    async with as_role("editor") as owner:
        _, post = await _amplify_with_post(client, owner)
    async with as_role("editor", email="intruder@test.local"):
        resp = await client.post(f"/v1/posts/{post['id']}/approve")
    assert resp.status_code == 403


async def test_skip_marks_skipped(client, as_role):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        resp = await client.post(f"/v1/posts/{post['id']}/skip")
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


async def test_cannot_approve_already_approved(client, as_role, db):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        await _connect(db, user.id)
        await client.post(f"/v1/posts/{post['id']}/approve")
        again = await client.post(f"/v1/posts/{post['id']}/approve")
    assert again.status_code == 409


async def test_missing_post_404(client, as_role):
    async with as_role("editor"):
        resp = await client.post(f"/v1/posts/{uuid.uuid4()}/approve")
    assert resp.status_code == 404
