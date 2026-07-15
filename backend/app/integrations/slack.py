"""Slack Web API client and request-signature verification.

A thin async wrapper over the handful of Slack methods super-hype needs to DM a
participant their bundled campaign actions and to update the card after they act:
resolve a Slack user by email, open a DM channel, post a message, and reply to an
interaction's ``response_url``. Inbound interaction payloads are authenticated
with ``verify_signature`` (HMAC-SHA256 over the raw body) before we trust them.

The client is transport-injectable so tests can stub every outbound call; nothing
here touches the database or imports higher layers.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings
from app.logger import get_logger

log = get_logger(__name__)

_SLACK_API_BASE = "https://slack.com/api"
# Reject a signed request whose timestamp is older than this, so a captured body
# cannot be replayed indefinitely (Slack's own recommended window).
_MAX_SIGNATURE_AGE_SECONDS = 60 * 5


class SlackError(Exception):
    """A Slack API call returned ok=false or failed at the transport level."""


class SlackClient:
    """Minimal async Slack Web API client. One instance per unit of work."""

    def __init__(
        self,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=_SLACK_API_BASE,
            transport=transport,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SlackClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def _call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self._client.post(f"/{method}", **kwargs)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if not data.get("ok", False):
            raise SlackError(f"slack {method} failed: {data.get('error', 'unknown')}")
        return data

    async def lookup_user_by_email(self, email: str) -> str | None:
        """Return the Slack user id for an email, or None if Slack has no match."""
        try:
            data = await self._call("users.lookupByEmail", data={"email": email})
        except SlackError as exc:
            # users_not_found is an expected miss (person not in the workspace),
            # not an error worth raising; it just means no DM can be sent.
            log.info("slack.lookup_user_by_email.miss", email=email, error=str(exc))
            return None
        user = data.get("user") or {}
        return user.get("id")

    async def open_dm(self, slack_user_id: str) -> str:
        """Open (or reuse) the bot's DM channel with a user and return its id."""
        data = await self._call("conversations.open", json={"users": slack_user_id})
        channel = data.get("channel") or {}
        return str(channel["id"])

    async def post_message(
        self, channel: str, *, text: str, blocks: list[dict[str, Any]] | None = None
    ) -> str:
        """Post a message to a channel and return its timestamp id.

        Unfurling is disabled so LinkedIn URLs in a card stay compact <url|label>
        hyperlinks instead of growing a preview attachment under the DM.
        """
        payload: dict[str, Any] = {
            "channel": channel,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if blocks is not None:
            payload["blocks"] = blocks
        data = await self._call("chat.postMessage", json=payload)
        return str(data["ts"])

    async def respond(self, response_url: str, payload: dict[str, Any]) -> None:
        """Reply to an interaction via its response_url (a full, absolute URL)."""
        resp = await self._client.post(response_url, json=payload)
        resp.raise_for_status()


def is_configured() -> bool:
    """True when both the bot token and signing secret are present."""
    return bool(settings.SLACK_BOT_TOKEN and settings.SLACK_SIGNING_SECRET)


def build_slack_client(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> SlackClient | None:
    """Construct a client from settings, or None when no bot token is set.

    A None return is how every caller degrades gracefully: the campaign flow runs
    with or without Slack, so an unconfigured deployment simply skips the DM.
    """
    token = settings.SLACK_BOT_TOKEN
    if not token:
        return None
    return SlackClient(token, transport=transport)


def verify_signature(
    *,
    signing_secret: str | None,
    timestamp: str | None,
    body: bytes,
    signature: str | None,
    now: datetime | None = None,
) -> bool:
    """Verify a Slack request signature (HMAC-SHA256 over ``v0:{ts}:{body}``).

    Returns False (never raises) on any missing part, a stale timestamp, or a
    mismatch, so the caller can answer a single 401 for every failure mode.
    """
    if not (signing_secret and timestamp and signature):
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    current = int((now or datetime.now(UTC)).timestamp())
    if abs(current - ts) > _MAX_SIGNATURE_AGE_SECONDS:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    digest = hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)
