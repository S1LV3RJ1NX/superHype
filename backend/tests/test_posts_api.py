"""API tests for per-post actions: edit, approve, skip, and ownership gating."""

import uuid

import pytest

pytestmark = pytest.mark.asyncio


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


async def test_owner_can_edit_then_approve(client, as_role, enqueued):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        edited = await client.patch(f"/v1/posts/{post['id']}", json={"body": "edited"})
        assert edited.status_code == 200
        assert edited.json()["body"] == "edited"

        approved = await client.post(f"/v1/posts/{post['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert any(name == "publish_post" for name, _, _ in enqueued)


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


async def test_cannot_approve_already_approved(client, as_role):
    async with as_role("editor") as user:
        _, post = await _amplify_with_post(client, user)
        await client.post(f"/v1/posts/{post['id']}/approve")
        again = await client.post(f"/v1/posts/{post['id']}/approve")
    assert again.status_code == 409


async def test_missing_post_404(client, as_role):
    async with as_role("editor"):
        resp = await client.post(f"/v1/posts/{uuid.uuid4()}/approve")
    assert resp.status_code == 404
