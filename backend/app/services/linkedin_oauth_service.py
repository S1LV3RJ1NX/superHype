"""LinkedIn OAuth 2.0 service: URL building, code exchange, identity, revoke.

Pure HTTP layer using httpx. No database access.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.config import settings

_AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
_REVOKE_URL = "https://www.linkedin.com/oauth/v2/revoke"

# Minimal scopes. The spec named r_basicprofile, but LinkedIn deprecated it
# (apps created after 2023-08-01 get unauthorized_scope_error). Identity now
# comes from OpenID Connect, so the true minimum is w_member_social (publish)
# plus openid+profile (member URN via /v2/userinfo). email is intentionally
# omitted; we do not use it.
_SCOPES = "w_member_social openid profile"


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
        scopes=data.get("scope", "").split(),
    )


async def fetch_identity(access_token: str) -> tuple[str, str]:
    """Fetch the member's URN and display name via the OIDC /v2/userinfo endpoint.

    The `sub` claim is the member id; the person URN is `urn:li:person:{sub}`.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    sub = data.get("sub", "")
    name = data.get("name", "")
    urn = f"urn:li:person:{sub}" if sub else ""
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
