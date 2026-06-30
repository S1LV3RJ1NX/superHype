"""Tests for the LinkedIn connection flow.

LinkedIn HTTP calls are mocked via monkeypatch on the service module.
Redis state is provided by the fakeredis fixture from conftest.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models.campaign import Campaign
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.services.linkedin_oauth_service import LinkedInTokens


@pytest.mark.asyncio
async def test_authorize_stores_state_in_redis(client, as_role, mock_redis):
    async with as_role("viewer") as _user:
        resp = await client.get("/v1/connections/linkedin/authorize")
    assert resp.status_code == 200
    data = resp.json()
    assert "authorize_url" in data
    assert "linkedin.com/oauth" in data["authorize_url"]

    keys = await mock_redis.keys("super-hype:li:state:*")
    assert len(keys) == 1


@pytest.mark.asyncio
async def test_callback_rejects_missing_state(client, as_role, mock_redis):
    async with as_role("viewer"):
        resp = await client.post(
            "/v1/connections/linkedin/callback",
            json={"code": "fake-code", "state": "nonexistent"},
        )
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_callback_rejects_foreign_state(client, as_role, mock_redis):
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    state = "test-state-foreign"
    await mock_redis.set(f"super-hype:li:state:{state}", str(user_a_id), ex=600)

    async with as_role("viewer", user_id=user_b_id):
        resp = await client.post(
            "/v1/connections/linkedin/callback",
            json={"code": "fake-code", "state": state},
        )
    assert resp.status_code == 400


_MOCK_TOKENS = LinkedInTokens(
    access_token="li-access-token-123",
    refresh_token="li-refresh-token-456",
    expires_at=datetime.now(UTC) + timedelta(days=60),
    scopes=["w_member_social", "r_basicprofile"],
)


@pytest.mark.asyncio
async def test_callback_stores_encrypted_token(client, as_role, mock_redis, db):
    user_id = uuid.uuid4()
    state = "test-state-enc"
    await mock_redis.set(f"super-hype:li:state:{state}", str(user_id), ex=600)

    with (
        patch(
            "app.controllers.connection_controller.linkedin_oauth_service.exchange_code",
            new_callable=AsyncMock,
            return_value=_MOCK_TOKENS,
        ),
        patch(
            "app.controllers.connection_controller.linkedin_oauth_service.fetch_identity",
            new_callable=AsyncMock,
            return_value=("urn:li:person:abc123", "Test User"),
        ),
    ):
        async with as_role("viewer", user_id=user_id):
            resp = await client.post(
                "/v1/connections/linkedin/callback",
                json={"code": "real-code", "state": state},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["display_name"] == "Test User"
    assert data["external_urn"] == "urn:li:person:abc123"

    from app.repositories.social_account_repo import social_account_repo

    account = await social_account_repo.get_by_user(db, user_id)
    assert account is not None
    assert isinstance(account.access_token_enc, bytes)
    assert account.access_token_enc != b"li-access-token-123"


@pytest.mark.asyncio
async def test_disconnect_deletes_row_and_audits(client, as_role, mock_redis, db):
    user_id = uuid.uuid4()
    state = "test-state-disc"
    await mock_redis.set(f"super-hype:li:state:{state}", str(user_id), ex=600)

    with (
        patch(
            "app.controllers.connection_controller.linkedin_oauth_service.exchange_code",
            new_callable=AsyncMock,
            return_value=_MOCK_TOKENS,
        ),
        patch(
            "app.controllers.connection_controller.linkedin_oauth_service.fetch_identity",
            new_callable=AsyncMock,
            return_value=("urn:li:person:del123", "Del User"),
        ),
    ):
        async with as_role("viewer", user_id=user_id) as _user:
            await client.post(
                "/v1/connections/linkedin/callback",
                json={"code": "code", "state": state},
            )

    with patch(
        "app.controllers.connection_controller.linkedin_oauth_service.revoke",
        new_callable=AsyncMock,
    ):
        async with as_role("viewer", user_id=user_id):
            resp = await client.delete("/v1/connections/linkedin")
    assert resp.status_code == 204

    from app.repositories.social_account_repo import social_account_repo

    assert await social_account_repo.get_by_user(db, user_id) is None

    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    result = await db.execute(
        select(AuditLog).where(
            AuditLog.actor_id == user_id,
            AuditLog.action == "linkedin_disconnected",
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_callback_linkedin_http_error_returns_400(client, as_role, mock_redis):
    user_id = uuid.uuid4()
    state = "test-state-httperr"
    await mock_redis.set(f"super-hype:li:state:{state}", str(user_id), ex=600)

    with patch(
        "app.controllers.connection_controller.linkedin_oauth_service.exchange_code",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError(
            "bad code",
            request=httpx.Request("POST", "https://x"),
            response=httpx.Response(400),
        ),
    ):
        async with as_role("viewer", user_id=user_id):
            resp = await client.post(
                "/v1/connections/linkedin/callback",
                json={"code": "expired-code", "state": state},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reconnect_returns_authorize_url(client, as_role, mock_redis):
    async with as_role("viewer"):
        resp = await client.post("/v1/connections/linkedin/reconnect")
    assert resp.status_code == 200
    assert "authorize_url" in resp.json()


@pytest.mark.asyncio
async def test_list_connections_empty(client, as_role, mock_redis):
    async with as_role("viewer"):
        resp = await client.get("/v1/connections")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_connections_after_connect(client, as_role, mock_redis):
    user_id = uuid.uuid4()
    state = "test-state-list"
    await mock_redis.set(f"super-hype:li:state:{state}", str(user_id), ex=600)

    with (
        patch(
            "app.controllers.connection_controller.linkedin_oauth_service.exchange_code",
            new_callable=AsyncMock,
            return_value=_MOCK_TOKENS,
        ),
        patch(
            "app.controllers.connection_controller.linkedin_oauth_service.fetch_identity",
            new_callable=AsyncMock,
            return_value=("urn:li:person:list1", "List User"),
        ),
    ):
        async with as_role("viewer", user_id=user_id):
            await client.post(
                "/v1/connections/linkedin/callback",
                json={"code": "code", "state": state},
            )

    async with as_role("viewer", user_id=user_id):
        resp = await client.get("/v1/connections")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["display_name"] == "List User"


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_connections(client):
    resp = await client.get("/v1/connections")
    assert resp.status_code in (401, 403)


def _account(*, status="active", expires_at=None):
    return SocialAccount(
        user_id=uuid.uuid4(),
        platform="linkedin",
        external_urn="urn:li:person:x",
        display_name="X",
        access_token_enc=b"enc",
        refresh_token_enc=None,
        scopes=["w_member_social"],
        expires_at=expires_at,
        status=status,
    )


def test_needs_reconnect_healthy():
    now = datetime.now(UTC)
    acct = _account(expires_at=now + timedelta(days=30))
    assert acct.requires_reconnect(now=now, buffer_hours=24) is False


def test_needs_reconnect_stale():
    now = datetime.now(UTC)
    acct = _account(status="stale", expires_at=now + timedelta(days=30))
    assert acct.requires_reconnect(now=now, buffer_hours=24) is True


def test_needs_reconnect_expired():
    now = datetime.now(UTC)
    acct = _account(expires_at=now - timedelta(days=1))
    assert acct.requires_reconnect(now=now, buffer_hours=24) is True


def test_needs_reconnect_within_buffer():
    now = datetime.now(UTC)
    acct = _account(expires_at=now + timedelta(hours=1))
    assert acct.requires_reconnect(now=now, buffer_hours=24) is True


def test_needs_reconnect_null_expiry():
    now = datetime.now(UTC)
    acct = _account(expires_at=None)
    assert acct.requires_reconnect(now=now, buffer_hours=24) is True


async def _pending_post(db, user_id):
    campaign = Campaign(
        title="C", type="amplify", status="publishing", created_by=user_id
    )
    db.add(campaign)
    await db.flush()
    post = Post(
        campaign_id=campaign.id,
        user_id=user_id,
        action="comment",
        body="hi",
        status="pending",
        idempotency_key=str(uuid.uuid4()),
    )
    db.add(post)
    await db.commit()
    return campaign, post


def _mock_oauth():
    return (
        patch(
            "app.controllers.connection_controller.linkedin_oauth_service.exchange_code",
            new_callable=AsyncMock,
            return_value=_MOCK_TOKENS,
        ),
        patch(
            "app.controllers.connection_controller.linkedin_oauth_service.fetch_identity",
            new_callable=AsyncMock,
            return_value=("urn:li:person:resume", "Resume User"),
        ),
    )


@pytest.mark.asyncio
async def test_callback_resumes_pending_post(client, as_role, mock_redis, db, enqueued):
    user_id = uuid.uuid4()
    state = "state-resume-ok"
    async with as_role("viewer", user_id=user_id):
        campaign, post = await _pending_post(db, user_id)
        await mock_redis.set(
            f"super-hype:li:state:{state}",
            json.dumps({"user_id": str(user_id), "resume_post_id": str(post.id)}),
            ex=600,
        )
        exchange_patch, identity_patch = _mock_oauth()
        with exchange_patch, identity_patch:
            resp = await client.post(
                "/v1/connections/linkedin/callback",
                json={"code": "real-code", "state": state},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["resumed_post_id"] == str(post.id)
    assert body["resumed_campaign_id"] == str(campaign.id)
    assert any(
        name == "publish_post" and args == (str(post.id),) for name, args, _ in enqueued
    )
    await db.refresh(post)
    assert post.status == "approved"
    # The post was planned with no account, so the resume must link the freshly
    # connected one or the worker would fail with "No connected LinkedIn account".
    assert post.social_account_id is not None


@pytest.mark.asyncio
async def test_callback_resume_owner_mismatch_skips(
    client, as_role, mock_redis, db, enqueued
):
    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    async with as_role("viewer", user_id=owner_id, email="owner@test.local"):
        _, post = await _pending_post(db, owner_id)

    state = "state-resume-foreign"
    async with as_role("viewer", user_id=other_id, email="other@test.local"):
        await mock_redis.set(
            f"super-hype:li:state:{state}",
            json.dumps({"user_id": str(other_id), "resume_post_id": str(post.id)}),
            ex=600,
        )
        exchange_patch, identity_patch = _mock_oauth()
        with exchange_patch, identity_patch:
            resp = await client.post(
                "/v1/connections/linkedin/callback",
                json={"code": "real-code", "state": state},
            )

    assert resp.status_code == 200
    assert resp.json()["resumed_post_id"] is None
    assert not any(name == "publish_post" for name, _, _ in enqueued)
    await db.refresh(post)
    assert post.status == "pending"


@pytest.mark.asyncio
async def test_callback_resume_idempotent_when_terminal(
    client, as_role, mock_redis, db, enqueued
):
    user_id = uuid.uuid4()
    state = "state-resume-terminal"
    async with as_role("viewer", user_id=user_id):
        _, post = await _pending_post(db, user_id)
        post.status = "skipped"
        await db.commit()
        await mock_redis.set(
            f"super-hype:li:state:{state}",
            json.dumps({"user_id": str(user_id), "resume_post_id": str(post.id)}),
            ex=600,
        )
        exchange_patch, identity_patch = _mock_oauth()
        with exchange_patch, identity_patch:
            resp = await client.post(
                "/v1/connections/linkedin/callback",
                json={"code": "real-code", "state": state},
            )

    assert resp.status_code == 200
    assert resp.json()["resumed_post_id"] is None
    assert not any(name == "publish_post" for name, _, _ in enqueued)
    await db.refresh(post)
    assert post.status == "skipped"
