"""Tests for the LinkedIn provider with a mocked httpx transport (no real calls)."""

import httpx
import pytest

from app.core.crypto import encrypt
from app.models.social_account import SocialAccount
from app.providers.linkedin import (
    LinkedInAuthError,
    LinkedInProvider,
    LinkedInRateLimitError,
)

pytestmark = pytest.mark.asyncio


def _account() -> SocialAccount:
    return SocialAccount(
        user_id=None,
        platform="linkedin",
        external_urn="urn:li:person:abc",
        display_name="Tester",
        access_token_enc=encrypt("token-123"),
        refresh_token_enc=encrypt("refresh-123"),
        scopes=["w_member_social"],
        status="active",
    )


def _provider(handler) -> LinkedInProvider:
    return LinkedInProvider(transport=httpx.MockTransport(handler))


async def test_publish_sends_correct_headers_and_returns_urn():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["version"] = request.headers.get("LinkedIn-Version")
        seen["protocol"] = request.headers.get("X-Restli-Protocol-Version")
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:9"})

    urn = await _provider(handler).publish(_account(), "Hello world")
    assert urn == "urn:li:share:9"
    assert seen["url"].endswith("/rest/posts")
    assert seen["version"]
    assert seen["protocol"] == "2.0.0"


async def test_publish_link_in_body_appends_url():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})

    await _provider(handler).publish(
        _account(), "Body text", link="https://ex.com", link_in_body=True
    )
    assert "https://ex.com" in captured["body"]["commentary"]


async def test_delete_post_issues_delete():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(204)

    await _provider(handler).delete_post(_account(), "urn:li:share:9")
    assert seen["method"] == "DELETE"
    # httpx decodes the percent-encoded URN back when exposing .path.
    assert seen["path"].endswith("/rest/posts/urn:li:share:9")


async def test_image_upload_three_step_returns_urn():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/rest/images"):
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.linkedin.com/abc",
                        "image": "urn:li:image:42",
                    }
                },
            )
        return httpx.Response(201)

    urn = await _provider(handler).upload_image(_account(), b"\x89PNG")
    assert urn == "urn:li:image:42"
    assert any("POST" in c and "/rest/images" in c for c in calls)
    assert any(c.startswith("PUT") for c in calls)


async def test_video_upload_initialize_put_finalize_returns_urn():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            f"{request.method} {request.url.query.decode() or request.url.path}"
        )
        if request.url.path.endswith("/rest/videos"):
            if b"initializeUpload" in request.url.query:
                return httpx.Response(
                    200,
                    json={
                        "value": {
                            "video": "urn:li:video:77",
                            "uploadToken": "tok",
                            "uploadInstructions": [
                                {
                                    "uploadUrl": "https://upload.linkedin.com/v",
                                    "firstByte": 0,
                                    "lastByte": 3,
                                }
                            ],
                        }
                    },
                )
            return httpx.Response(200)  # finalize
        return httpx.Response(200, headers={"etag": "part-1"})  # PUT chunk

    urn = await _provider(handler).upload_video(_account(), b"\x00\x00\x00\x18")
    assert urn == "urn:li:video:77"
    assert any("initializeUpload" in c for c in calls)
    assert any(c.startswith("PUT") for c in calls)
    assert any("finalizeUpload" in c for c in calls)


async def test_comment_returns_urn():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/rest/socialActions/" in request.url.path
        assert "/comments" in request.url.path
        return httpx.Response(201, headers={"x-restli-id": "urn:li:comment:5"})

    urn = await _provider(handler).comment(
        _account(), "urn:li:activity:1", "great post"
    )
    assert urn == "urn:li:comment:5"


async def test_401_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid token")

    with pytest.raises(LinkedInAuthError):
        await _provider(handler).like(_account(), "urn:li:activity:1")


async def test_429_raises_rate_limit_with_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "30"}, text="slow down")

    with pytest.raises(LinkedInRateLimitError) as exc:
        await _provider(handler).publish(_account(), "hi")
    assert exc.value.retry_after == 30


async def test_refresh_invalid_grant_raises_auth_error():
    # The token endpoint reports a dead refresh token as 400 invalid_grant
    # (RFC 6749), not 401; it must map to the auth error so the worker marks
    # the account stale and asks to reconnect.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(LinkedInAuthError):
        await _provider(handler).refresh(_account())


async def test_reshare_uses_reshare_context():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:7"})

    urn = await _provider(handler).reshare(
        _account(), "urn:li:activity:99", "check this out"
    )
    assert urn == "urn:li:share:7"
    assert captured["body"]["reshareContext"]["parent"] == "urn:li:activity:99"
