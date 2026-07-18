"""Tests for the X (Twitter) connection flow: PKCE authorize, callback, disconnect.

X HTTP calls are mocked via patch on the controller's service module. Redis
state is provided by the fakeredis fixture from conftest.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.x_oauth_service import XTokens, generate_pkce

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _x_configured(monkeypatch):
    """The X connector is hidden unless a client id is configured; tests opt in."""
    from app.config import settings

    monkeypatch.setattr(settings, "X_CLIENT_ID", "x-client-id")
    monkeypatch.setattr(settings, "X_CLIENT_SECRET", "x-client-secret")


_MOCK_TOKENS = XTokens(
    access_token="x-access-token-123",
    refresh_token="x-refresh-token-456",
    expires_at=datetime.now(UTC) + timedelta(hours=2),
    scopes=["tweet.read", "tweet.write", "offline.access"],
)


def _mock_oauth(x_user_id="9000001", name="Test User"):
    return (
        patch(
            "app.controllers.connection_controller.x_oauth_service.exchange_code",
            new_callable=AsyncMock,
            return_value=_MOCK_TOKENS,
        ),
        patch(
            "app.controllers.connection_controller.x_oauth_service.fetch_identity",
            new_callable=AsyncMock,
            return_value=(x_user_id, name),
        ),
    )


async def test_authorize_stores_state_and_verifier_in_redis(
    client, as_role, mock_redis
):
    async with as_role("viewer"):
        resp = await client.get("/v1/connections/x/authorize")
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert url.startswith("https://x.com/i/oauth2/authorize")

    params = parse_qs(urlparse(url).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"][0]
    # The verifier never appears in the browser-facing URL; it lives in Redis.
    keys = await mock_redis.keys("super-hype:x:state:*")
    assert len(keys) == 1
    stored = json.loads(await mock_redis.get(keys[0]))
    assert stored["code_verifier"]
    assert stored["code_verifier"] not in url


async def test_authorize_503_when_x_not_configured(
    client, as_role, mock_redis, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "X_CLIENT_ID", None)
    async with as_role("viewer"):
        resp = await client.get("/v1/connections/x/authorize")
    assert resp.status_code == 503


async def test_callback_rejects_missing_state(client, as_role, mock_redis):
    async with as_role("viewer"):
        resp = await client.post(
            "/v1/connections/x/callback",
            json={"code": "fake-code", "state": "nonexistent"},
        )
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.json()["detail"]


async def test_callback_rejects_foreign_state(client, as_role, mock_redis):
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    state = "x-state-foreign"
    await mock_redis.set(
        f"super-hype:x:state:{state}",
        json.dumps({"user_id": str(user_a_id), "code_verifier": "v"}),
        ex=600,
    )

    async with as_role("viewer", user_id=user_b_id):
        resp = await client.post(
            "/v1/connections/x/callback",
            json={"code": "fake-code", "state": state},
        )
    assert resp.status_code == 400


async def test_callback_replays_verifier_and_stores_ciphertext(
    client, as_role, mock_redis, db
):
    user_id = uuid.uuid4()
    state = "x-state-enc"
    await mock_redis.set(
        f"super-hype:x:state:{state}",
        json.dumps({"user_id": str(user_id), "code_verifier": "the-verifier"}),
        ex=600,
    )

    exchange_patch, identity_patch = _mock_oauth()
    with exchange_patch as exchange, identity_patch:
        async with as_role("viewer", user_id=user_id):
            resp = await client.post(
                "/v1/connections/x/callback",
                json={"code": "real-code", "state": state},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "x"
    assert data["status"] == "active"
    assert data["display_name"] == "Test User"
    assert data["external_urn"] == "9000001"
    # The stored PKCE verifier is what the exchange replays.
    assert exchange.await_args.args == ("real-code", "the-verifier")

    from app.repositories.social_account_repo import social_account_repo

    account = await social_account_repo.get_by_user(db, user_id, platform="x")
    assert account is not None
    assert isinstance(account.access_token_enc, bytes)
    assert account.access_token_enc != b"x-access-token-123"
    # offline.access grants a refresh token; it must be stored encrypted too.
    assert account.refresh_token_enc is not None
    assert account.refresh_token_enc != b"x-refresh-token-456"


async def test_x_connection_does_not_clobber_linkedin(client, as_role, mock_redis, db):
    """One row per platform: connecting X must not replace a LinkedIn row."""
    from app.core.crypto import encrypt
    from app.models.social_account import SocialAccount
    from app.repositories.social_account_repo import social_account_repo

    user_id = uuid.uuid4()
    async with as_role("viewer", user_id=user_id):
        db.add(
            SocialAccount(
                user_id=user_id,
                platform="linkedin",
                external_urn="urn:li:person:keep",
                display_name="Keep Me",
                access_token_enc=encrypt("li-tok"),
                refresh_token_enc=None,
                scopes=["w_member_social"],
                status="active",
            )
        )
        await db.commit()

        state = "x-state-both"
        await mock_redis.set(
            f"super-hype:x:state:{state}",
            json.dumps({"user_id": str(user_id), "code_verifier": "v"}),
            ex=600,
        )
        exchange_patch, identity_patch = _mock_oauth()
        with exchange_patch, identity_patch:
            resp = await client.post(
                "/v1/connections/x/callback",
                json={"code": "code", "state": state},
            )
        assert resp.status_code == 200

        li = await social_account_repo.get_by_user(db, user_id, platform="linkedin")
        x = await social_account_repo.get_by_user(db, user_id, platform="x")
    assert li is not None and li.external_urn == "urn:li:person:keep"
    assert x is not None and x.external_urn == "9000001"

    async with as_role("viewer", user_id=user_id):
        listing = await client.get("/v1/connections")
    platforms = {item["platform"] for item in listing.json()}
    assert platforms == {"linkedin", "x"}


async def test_disconnect_x_deletes_row_and_audits(client, as_role, mock_redis, db):
    user_id = uuid.uuid4()
    state = "x-state-disc"
    await mock_redis.set(
        f"super-hype:x:state:{state}",
        json.dumps({"user_id": str(user_id), "code_verifier": "v"}),
        ex=600,
    )

    exchange_patch, identity_patch = _mock_oauth(x_user_id="9000002", name="Del User")
    with exchange_patch, identity_patch:
        async with as_role("viewer", user_id=user_id):
            await client.post(
                "/v1/connections/x/callback",
                json={"code": "code", "state": state},
            )

    with patch(
        "app.controllers.connection_controller.x_oauth_service.revoke",
        new_callable=AsyncMock,
    ) as revoke:
        async with as_role("viewer", user_id=user_id):
            resp = await client.delete("/v1/connections/x")
    assert resp.status_code == 204
    assert revoke.await_count == 1

    from app.repositories.social_account_repo import social_account_repo

    assert await social_account_repo.get_by_user(db, user_id, platform="x") is None

    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    result = await db.execute(
        select(AuditLog).where(
            AuditLog.actor_id == user_id,
            AuditLog.action == "x_disconnected",
        )
    )
    assert result.scalar_one_or_none() is not None


async def test_reconnect_x_returns_authorize_url(client, as_role, mock_redis):
    async with as_role("viewer"):
        resp = await client.post("/v1/connections/x/reconnect")
    assert resp.status_code == 200
    assert "authorize_url" in resp.json()


async def test_callback_resumes_pending_x_post(
    client, as_role, mock_redis, db, enqueued
):
    from app.models.campaign import Campaign
    from app.models.post import Post

    user_id = uuid.uuid4()
    async with as_role("viewer", user_id=user_id):
        campaign = Campaign(
            title="C",
            type="amplify",
            platform="x",
            status="publishing",
            created_by=user_id,
        )
        db.add(campaign)
        await db.flush()
        post = Post(
            campaign_id=campaign.id,
            user_id=user_id,
            platform="x",
            action="comment",
            body="hi",
            status="pending",
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(post)
        await db.commit()

        state = "x-state-resume"
        await mock_redis.set(
            f"super-hype:x:state:{state}",
            json.dumps(
                {
                    "user_id": str(user_id),
                    "resume_post_id": str(post.id),
                    "code_verifier": "v",
                }
            ),
            ex=600,
        )
        exchange_patch, identity_patch = _mock_oauth()
        with exchange_patch, identity_patch:
            resp = await client.post(
                "/v1/connections/x/callback",
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
    assert post.social_account_id is not None


async def test_callback_refires_held_notifications(
    client, as_role, mock_redis, db, enqueued
):
    """Reconnecting fires the approve card we held while the token was stale.

    A pending X post with no resume target (the person got a reconnect-first DM,
    not an approve card) must, once the account is live again, re-enqueue
    notify_participant for that campaign so the card finally goes out.
    """
    from app.models.campaign import Campaign
    from app.models.post import Post

    user_id = uuid.uuid4()
    async with as_role("viewer", user_id=user_id):
        campaign = Campaign(
            title="C",
            type="amplify",
            platform="x",
            status="publishing",
            created_by=user_id,
        )
        db.add(campaign)
        await db.flush()
        post = Post(
            campaign_id=campaign.id,
            user_id=user_id,
            platform="x",
            action="like",
            status="pending",
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(post)
        await db.commit()

        state = "x-state-refire"
        await mock_redis.set(
            f"super-hype:x:state:{state}",
            json.dumps({"user_id": str(user_id), "code_verifier": "v"}),
            ex=600,
        )
        exchange_patch, identity_patch = _mock_oauth()
        with exchange_patch, identity_patch:
            resp = await client.post(
                "/v1/connections/x/callback",
                json={"code": "real-code", "state": state},
            )

    assert resp.status_code == 200
    assert resp.json()["resumed_post_id"] is None
    assert any(
        name == "notify_participant" and args == (str(campaign.id), str(user_id))
        for name, args, _ in enqueued
    )


async def test_callback_does_not_resume_post_from_another_platform(
    client, as_role, mock_redis, db, enqueued
):
    """An X connect must never approve (or link its account to) a LinkedIn post:
    the worker routes by post.platform, so a mismatched account would send one
    platform's token to the other's API."""
    from app.models.campaign import Campaign
    from app.models.post import Post

    user_id = uuid.uuid4()
    async with as_role("viewer", user_id=user_id):
        campaign = Campaign(
            title="C",
            type="amplify",
            platform="linkedin",
            status="publishing",
            created_by=user_id,
        )
        db.add(campaign)
        await db.flush()
        post = Post(
            campaign_id=campaign.id,
            user_id=user_id,
            platform="linkedin",
            action="comment",
            body="hi",
            status="pending",
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(post)
        await db.commit()

        state = "x-state-cross-platform"
        await mock_redis.set(
            f"super-hype:x:state:{state}",
            json.dumps(
                {
                    "user_id": str(user_id),
                    "resume_post_id": str(post.id),
                    "code_verifier": "v",
                }
            ),
            ex=600,
        )
        exchange_patch, identity_patch = _mock_oauth()
        with exchange_patch, identity_patch:
            resp = await client.post(
                "/v1/connections/x/callback",
                json={"code": "real-code", "state": state},
            )

    assert resp.status_code == 200
    assert resp.json()["resumed_post_id"] is None
    assert not any(name == "publish_post" for name, _, _ in enqueued)
    await db.refresh(post)
    assert post.status == "pending"
    assert post.social_account_id is None


async def test_generate_pkce_challenge_matches_verifier():
    import base64
    import hashlib

    verifier, challenge = generate_pkce()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    # Fresh randomness per call.
    assert generate_pkce()[0] != verifier
