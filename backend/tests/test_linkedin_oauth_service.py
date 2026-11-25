"""HTTP-level tests for the LinkedIn OAuth service: requested scopes and identity.

The connection-flow tests mock fetch_identity away at the controller boundary,
so this suite checks the request shaping it owns. Requests are routed through a
MockTransport by patching httpx.AsyncClient to inject it.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services import linkedin_oauth_service

pytestmark = pytest.mark.asyncio


@pytest.fixture
def route(monkeypatch):
    captured: list[httpx.Request] = []
    responses: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return responses.get(request.url.path) or httpx.Response(
            500, text="unrouted path"
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(linkedin_oauth_service.httpx, "AsyncClient", client_factory)
    return captured, responses


async def test_authorize_url_requests_community_management_scopes_without_oidc():
    url = linkedin_oauth_service.authorize_url("st")
    scopes = parse_qs(urlparse(url).query)["scope"][0].split()
    assert set(scopes) == {"w_member_social", "w_member_social_feed", "r_basicprofile"}


async def test_fetch_identity_uses_v2_me(route):
    captured, responses = route
    responses["/v2/me"] = httpx.Response(
        200,
        json={"id": "abc123", "localizedFirstName": "Ada", "localizedLastName": "L"},
    )

    urn, name = await linkedin_oauth_service.fetch_identity("the-token")

    assert urn == "urn:li:person:abc123"
    assert name == "Ada L"
    assert captured[0].headers["Authorization"] == "Bearer the-token"
