"""Tests for the X provider with a mocked httpx transport (no real calls)."""

import json

import httpx
import pytest

from app.core.crypto import encrypt
from app.models.social_account import SocialAccount
from app.providers.base import (
    ProviderAPIError,
    ProviderAuthError,
    ProviderRateLimitError,
)
from app.providers.x import XAPIError, XAuthError, XProvider, XRateLimitError

pytestmark = pytest.mark.asyncio


def _account() -> SocialAccount:
    return SocialAccount(
        user_id=None,
        platform="x",
        external_urn="9000001",
        display_name="Tester",
        access_token_enc=encrypt("x-token-123"),
        refresh_token_enc=encrypt("x-refresh-456"),
        scopes=["tweet.write", "like.write"],
        status="active",
    )


def _provider(handler) -> XProvider:
    return XProvider(transport=httpx.MockTransport(handler))


async def test_publish_posts_tweet_and_returns_id():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"id": "111", "text": "hi"}})

    tweet_id = await _provider(handler).publish(_account(), "hi")
    assert tweet_id == "111"
    assert seen["path"] == "/2/tweets"
    assert seen["auth"] == "Bearer x-token-123"
    assert seen["body"] == {"text": "hi"}


async def test_publish_link_in_body_appends_url():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"id": "1"}})

    await _provider(handler).publish(
        _account(), "Body text", link="https://ex.com", link_in_body=True
    )
    assert "https://ex.com" in captured["body"]["text"]


async def test_publish_with_media_attaches_media_ids():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"id": "1"}})

    await _provider(handler).publish(_account(), "pic", image_urn="555")
    assert captured["body"]["media"] == {"media_ids": ["555"]}


async def test_reshare_is_a_quote_tweet():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"id": "222"}})

    tweet_id = await _provider(handler).reshare(_account(), "999", "my take")
    assert tweet_id == "222"
    assert captured["body"]["quote_tweet_id"] == "999"
    assert captured["body"]["text"] == "my take"


async def test_comment_is_a_reply():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"id": "333"}})

    tweet_id = await _provider(handler).comment(_account(), "999", "nice one")
    assert tweet_id == "333"
    assert captured["body"]["reply"] == {"in_reply_to_tweet_id": "999"}


async def test_like_hits_user_scoped_endpoint():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"liked": True}})

    await _provider(handler).like(_account(), "999")
    assert seen["path"] == "/2/users/9000001/likes"
    assert seen["body"] == {"tweet_id": "999"}


async def test_bookmark_hits_user_scoped_endpoint():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"bookmarked": True}})

    await _provider(handler).bookmark(_account(), "999")
    assert seen["path"] == "/2/users/9000001/bookmarks"
    assert seen["body"] == {"tweet_id": "999"}


async def test_delete_post_issues_delete():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": {"deleted": True}})

    await _provider(handler).delete_post(_account(), "111")
    assert seen["method"] == "DELETE"
    assert seen["path"] == "/2/tweets/111"


async def test_upload_image_returns_media_id_and_sets_alt():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/2/media/upload"):
            return httpx.Response(200, json={"data": {"id": "777"}})
        return httpx.Response(200, json={})  # metadata (alt text)

    media_id = await _provider(handler).upload_image(
        _account(), b"\x89PNG", alt="a chart"
    )
    assert media_id == "777"
    assert "/2/media/upload" in calls
    assert "/2/media/metadata" in calls


async def test_upload_image_alt_failure_does_not_fail_upload():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/2/media/upload"):
            return httpx.Response(200, json={"data": {"id": "778"}})
        return httpx.Response(400, text="bad alt")

    media_id = await _provider(handler).upload_image(_account(), b"img", alt="x")
    assert media_id == "778"


async def test_upload_video_chunked_init_append_finalize():
    commands: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode(errors="ignore")
        for cmd in ("INIT", "APPEND", "FINALIZE"):
            if cmd in body:
                commands.append(cmd)
                break
        return httpx.Response(200, json={"data": {"id": "888"}})

    media_id = await _provider(handler).upload_video(_account(), b"\x00" * 16)
    assert media_id == "888"
    assert commands == ["INIT", "APPEND", "FINALIZE"]


async def test_refresh_posts_refresh_grant():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 7200,
            },
        )

    data = await _provider(handler).refresh(_account())
    assert captured["path"] == "/2/oauth2/token"
    assert "grant_type=refresh_token" in captured["body"]
    assert "x-refresh-456" in captured["body"]
    assert data["access_token"] == "new-access"
    assert data["refresh_token"] == "new-refresh"


async def test_refresh_invalid_grant_raises_auth_error():
    # A dead or already-rotated refresh token comes back from the token
    # endpoint as 400 invalid_grant (RFC 6749), not 401. It must map to the
    # auth error so the worker marks the account stale and asks to reconnect.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "revoked"}
        )

    with pytest.raises(ProviderAuthError):
        await _provider(handler).refresh(_account())


async def test_refresh_without_refresh_token_raises_auth_error():
    acct = _account()
    acct.refresh_token_enc = None

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP call expected")

    with pytest.raises(XAuthError):
        await _provider(handler).refresh(acct)


async def test_insights_returns_public_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/tweets/111"
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "111",
                    "public_metrics": {"like_count": 5, "reply_count": 2},
                }
            },
        )

    metrics = await _provider(handler).insights(_account(), "111")
    assert metrics == {"like_count": 5, "reply_count": 2}


async def test_401_raises_auth_error_on_shared_hierarchy():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid token")

    with pytest.raises(XAuthError) as exc:
        await _provider(handler).like(_account(), "999")
    # The worker's generic handling keys off the shared base classes.
    assert isinstance(exc.value, ProviderAuthError)
    assert isinstance(exc.value, ProviderAPIError)


async def test_429_raises_rate_limit_with_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "30"}, text="slow down")

    with pytest.raises(XRateLimitError) as exc:
        await _provider(handler).publish(_account(), "hi")
    assert isinstance(exc.value, ProviderRateLimitError)
    assert exc.value.retry_after == 30


async def test_429_reads_rate_limit_reset_header(monkeypatch):
    import app.providers.x as x_mod

    monkeypatch.setattr(x_mod.time, "time", lambda: 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, headers={"x-rate-limit-reset": "1090"}, text="throttled"
        )

    with pytest.raises(XRateLimitError) as exc:
        await _provider(handler).publish(_account(), "hi")
    assert exc.value.retry_after == 90


async def test_other_4xx_raises_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with pytest.raises(XAPIError) as exc:
        await _provider(handler).publish(_account(), "hi")
    assert exc.value.status_code == 403


async def test_publish_missing_tweet_id_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"data": {}})

    with pytest.raises(XAPIError, match="No tweet id"):
        await _provider(handler).publish(_account(), "hi")
