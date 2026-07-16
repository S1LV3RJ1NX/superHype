"""HTTP-level tests for the X OAuth service: code exchange, identity, revoke.

The connection-flow tests (test_x_connections.py) mock these functions away at
the controller boundary, so this suite exercises the request shaping they own
for real: PKCE verifier and form fields on the token exchange, HTTP Basic
client auth, token payload parsing and defaults, and revoke's best-effort
error swallowing. Requests are routed through a MockTransport by patching
httpx.AsyncClient to inject it.
"""

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from app.services import x_oauth_service

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _x_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "X_CLIENT_ID", "x-client-id")
    monkeypatch.setattr(settings, "X_CLIENT_SECRET", "x-client-secret")


@pytest.fixture
def route(monkeypatch):
    """Capture requests and serve canned responses keyed by URL path."""
    captured: list[httpx.Request] = []
    responses: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return responses.get(request.url.path) or httpx.Response(
            500, text="unrouted path"
        )

    transport = httpx.MockTransport(handler)
    orig_client = httpx.AsyncClient

    def client_with_transport(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_with_transport)
    return captured, responses


async def test_exchange_code_sends_pkce_form_and_basic_auth(route):
    captured, responses = route
    responses["/2/oauth2/token"] = httpx.Response(
        200,
        json={
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
            "scope": "tweet.read tweet.write offline.access",
        },
    )

    tokens = await x_oauth_service.exchange_code("the-code", "the-verifier")

    req = captured[0]
    form = parse_qs(req.content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["the-code"]
    assert form["code_verifier"] == ["the-verifier"]
    assert form["client_id"] == ["x-client-id"]
    assert form["redirect_uri"] == [x_oauth_service.redirect_uri()]
    expected_basic = base64.b64encode(b"x-client-id:x-client-secret").decode()
    assert req.headers["authorization"] == f"Basic {expected_basic}"

    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"
    assert tokens.scopes == ["tweet.read", "tweet.write", "offline.access"]
    assert tokens.expires_at <= datetime.now(UTC) + timedelta(seconds=3600)
    assert tokens.expires_at > datetime.now(UTC) + timedelta(seconds=3500)


async def test_exchange_code_defaults_missing_fields(route):
    # X's default token lifetime is two hours; refresh_token and scope are
    # absent when offline.access was not granted.
    captured, responses = route
    responses["/2/oauth2/token"] = httpx.Response(200, json={"access_token": "at"})

    tokens = await x_oauth_service.exchange_code("c", "v")

    assert tokens.refresh_token is None
    assert tokens.scopes == []
    assert tokens.expires_at <= datetime.now(UTC) + timedelta(seconds=7200)
    assert tokens.expires_at > datetime.now(UTC) + timedelta(seconds=7100)


async def test_exchange_code_raises_on_error_status(route):
    captured, responses = route
    responses["/2/oauth2/token"] = httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(httpx.HTTPStatusError):
        await x_oauth_service.exchange_code("bad-code", "v")


async def test_fetch_identity_sends_bearer_and_parses_payload(route):
    captured, responses = route
    responses["/2/users/me"] = httpx.Response(
        200, json={"data": {"id": 9000001, "name": "Ada"}}
    )

    x_user_id, name = await x_oauth_service.fetch_identity("the-token")

    assert captured[0].headers["authorization"] == "Bearer the-token"
    assert x_user_id == "9000001"
    assert name == "Ada"


async def test_revoke_posts_token_and_ignores_error_status(route):
    captured, responses = route
    responses["/2/oauth2/revoke"] = httpx.Response(400, text="nope")

    await x_oauth_service.revoke("the-token")

    form = parse_qs(captured[0].content.decode())
    assert form["token"] == ["the-token"]
    assert form["token_type_hint"] == ["access_token"]


async def test_revoke_swallows_transport_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    transport = httpx.MockTransport(handler)
    orig_client = httpx.AsyncClient

    def client_with_transport(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_with_transport)

    # Best effort by design: a dead revoke endpoint must not block disconnect.
    await x_oauth_service.revoke("the-token")
