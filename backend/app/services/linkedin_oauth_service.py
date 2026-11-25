"""LinkedIn OAuth 2.0 service: URL building, code exchange, identity, revoke.

Pure HTTP layer using httpx. No database access.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.config import settings

_AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_ME_URL = "https://api.linkedin.com/v2/me"
_REVOKE_URL = "https://www.linkedin.com/oauth/v2/revoke"

# The app holds the Community Management API, which LinkedIn requires to be the
# only product on the app, so OpenID Connect (openid, profile) is unavailable and
# requesting it fails with unauthorized_scope_error. Identity comes from
# r_basicprofile via /v2/me instead. w_member_social publishes and reshares;
# w_member_social_feed covers comments and likes (socialActions).
_SCOPES = "w_member_social w_member_social_feed r_basicprofile"


@dataclass(frozen=True)
class LinkedInTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: list[str]


def authorize_url(state: str) -> str:
    """Build the LinkedIn OAuth 2.0 authorization URL."""
    params = {
        "response_type": "code",
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "redirect_uri": f"{settings.FRONTEND_URL}/connections/linkedin/callback",
        "scope": _SCOPES,
        "state": state,
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> LinkedInTokens:
    """Exchange an authorization code for tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{settings.FRONTEND_URL}/connections/linkedin/callback",
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()

    expires_in = int(data.get("expires_in", 5184000))  # default 60 days
    return LinkedInTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        # LinkedIn returns the granted scopes comma-separated, not space-separated.
        scopes=[s for s in re.split(r"[,\s]+", data.get("scope", "")) if s],
    )


async def fetch_identity(access_token: str) -> tuple[str, str]:
    """Fetch the member's URN and display name via /v2/me (r_basicprofile).

    `id` is the same member id OIDC returned as `sub`, so URNs of accounts
    connected before the switch stay stable: `urn:li:person:{id}`.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _ME_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    member_id = data.get("id", "")
    name = " ".join(
        part
        for part in (data.get("localizedFirstName"), data.get("localizedLastName"))
        if part
    )
    urn = f"urn:li:person:{member_id}" if member_id else ""
    return urn, name


async def revoke(access_token: str) -> None:
    """Best-effort token revocation. Errors are swallowed."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                _REVOKE_URL,
                data={
                    "client_id": settings.LINKEDIN_CLIENT_ID,
                    "client_secret": settings.LINKEDIN_CLIENT_SECRET,
                    "token": access_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError:
        pass
