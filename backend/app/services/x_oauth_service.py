"""X (Twitter) OAuth 2.0 PKCE service: URL building, code exchange, identity, revoke.

Pure HTTP layer using httpx. No database access. X requires PKCE on every
authorization-code flow; the app is a confidential web client, so the token
endpoint additionally takes HTTP Basic auth with the client id and secret.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.config import settings

_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"

# tweet.read and users.read are baseline (every write scope requires them and
# /2/users/me needs them). tweet.write covers posts, replies, and quote posts;
# like.write and bookmark.write cover the engagement actions; media.write is
# the v2 media upload; offline.access grants the rotating refresh token that
# keeps the ~2h access tokens alive without re-consent.
_SCOPES = (
    "tweet.read tweet.write users.read like.write bookmark.write "
    "media.write offline.access"
)


@dataclass(frozen=True)
class XTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: list[str]


def _token_url() -> str:
    return f"{settings.X_API_BASE_URL.rstrip('/')}/2/oauth2/token"


def redirect_uri() -> str:
    return f"{settings.FRONTEND_URL}/connections/x/callback"


def generate_pkce() -> tuple[str, str]:
    """Return a fresh (code_verifier, code_challenge) pair (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(state: str, code_challenge: str) -> str:
    """Build the X OAuth 2.0 authorization URL."""
    params = {
        "response_type": "code",
        "client_id": settings.X_CLIENT_ID or "",
        "redirect_uri": redirect_uri(),
        "scope": _SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str, code_verifier: str) -> XTokens:
    """Exchange an authorization code (plus its PKCE verifier) for tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _token_url(),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(),
                "client_id": settings.X_CLIENT_ID or "",
                "code_verifier": code_verifier,
            },
            auth=(settings.X_CLIENT_ID or "", settings.X_CLIENT_SECRET or ""),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()

    expires_in = int(data.get("expires_in", 7200))  # X default: 2 hours
    return XTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        scopes=data.get("scope", "").split(),
    )


async def fetch_identity(access_token: str) -> tuple[str, str]:
    """Fetch the member's numeric user id and display name via /2/users/me."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.X_API_BASE_URL.rstrip('/')}/2/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json().get("data") or {}

    return str(data.get("id", "")), str(data.get("name", ""))


async def revoke(access_token: str) -> None:
    """Best-effort token revocation. Errors are swallowed."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{settings.X_API_BASE_URL.rstrip('/')}/2/oauth2/revoke",
                data={
                    "token": access_token,
                    "client_id": settings.X_CLIENT_ID or "",
                    "token_type_hint": "access_token",
                },
                auth=(settings.X_CLIENT_ID or "", settings.X_CLIENT_SECRET or ""),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError:
        pass
