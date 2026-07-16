"""X (Twitter) provider: tweets, quote tweets, replies, likes, bookmarks, media.

Uses the v2 API with httpx. Tokens are decrypted only here, never logged.
Errors are typed on the shared provider hierarchy so the worker's retry policy
(auth -> reconnect, 429 -> delayed retry, other 4xx -> fail fast) applies
unchanged. The account's external_urn holds the numeric X user id; post ids and
media ids are plain numeric strings.
"""

import time
from typing import Any

import httpx

from app.config import settings
from app.core.crypto import decrypt
from app.logger import get_logger
from app.models.social_account import SocialAccount
from app.providers.base import (
    ProviderAPIError,
    ProviderAuthError,
    ProviderRateLimitError,
)

log = get_logger(__name__)

_TIMEOUT = httpx.Timeout(30.0)
# Chunk size for the chunked media upload (APPEND accepts up to 5 MB per part).
_MEDIA_CHUNK_BYTES = 4 * 1024 * 1024


class XAPIError(ProviderAPIError):
    """An X API call failed for a non-auth, non-rate-limit reason."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"X API error {status_code}: {message}")


class XAuthError(XAPIError, ProviderAuthError):
    """401: the token is invalid or revoked. Non-retryable; mark the account stale."""


class XRateLimitError(XAPIError, ProviderRateLimitError):
    """429: throttled. Retryable after retry_after seconds."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(429, message)


def _retry_after_from(resp: httpx.Response) -> int | None:
    """Seconds until the window resets, from retry-after or x-rate-limit-reset."""
    retry_after = resp.headers.get("retry-after")
    if retry_after and retry_after.isdigit():
        return int(retry_after)
    reset = resp.headers.get("x-rate-limit-reset")
    if reset and reset.isdigit():
        return max(int(reset) - int(time.time()), 1)
    return None


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    body = resp.text[:300]
    if resp.status_code == 401:
        raise XAuthError(401, body)
    if resp.status_code == 429:
        raise XRateLimitError(body, _retry_after_from(resp))
    raise XAPIError(resp.status_code, body)


class XProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # transport is injectable so tests can route calls through a MockTransport.
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport)

    def _base(self) -> str:
        return settings.X_API_BASE_URL.rstrip("/")

    def _headers(self, acct: SocialAccount) -> dict[str, str]:
        token = decrypt(acct.access_token_enc)
        return {"Authorization": f"Bearer {token}"}

    async def _create_tweet(self, acct: SocialAccount, payload: dict[str, Any]) -> str:
        async with self._client() as client:
            resp = await client.post(
                f"{self._base()}/2/tweets",
                headers=self._headers(acct),
                json=payload,
            )
            _raise_for_status(resp)
        tweet_id = (resp.json().get("data") or {}).get("id")
        if not tweet_id:
            raise XAPIError(resp.status_code, "No tweet id in response body.")
        return str(tweet_id)

    async def publish(
        self,
        acct: SocialAccount,
        text: str,
        *,
        link: str | None = None,
        link_in_body: bool = False,
        image_urn: str | None = None,
        reshare_of: str | None = None,
    ) -> str:
        body = text
        if link and link_in_body:
            body = f"{text}\n\n{link}".strip()
        payload: dict[str, Any] = {"text": body}
        if image_urn:
            payload["media"] = {"media_ids": [image_urn]}
        if reshare_of:
            payload["quote_tweet_id"] = reshare_of
        return await self._create_tweet(acct, payload)

    async def comment(
        self,
        acct: SocialAccount,
        target_urn: str,
        text: str,
    ) -> str:
        """A comment on X is a reply tweet under the target."""
        return await self._create_tweet(
            acct,
            {"text": text, "reply": {"in_reply_to_tweet_id": target_urn}},
        )

    async def reshare(
        self,
        acct: SocialAccount,
        target_urn: str,
        commentary: str = "",
    ) -> str:
        """A reshare with commentary on X is a quote tweet."""
        return await self.publish(acct, commentary, reshare_of=target_urn)

    async def like(
        self,
        acct: SocialAccount,
        target_urn: str,
    ) -> None:
        async with self._client() as client:
            resp = await client.post(
                f"{self._base()}/2/users/{acct.external_urn}/likes",
                headers=self._headers(acct),
                json={"tweet_id": target_urn},
            )
            _raise_for_status(resp)

    async def bookmark(
        self,
        acct: SocialAccount,
        target_urn: str,
    ) -> None:
        async with self._client() as client:
            resp = await client.post(
                f"{self._base()}/2/users/{acct.external_urn}/bookmarks",
                headers=self._headers(acct),
                json={"tweet_id": target_urn},
            )
            _raise_for_status(resp)

    async def delete_post(self, acct: SocialAccount, urn: str) -> None:
        """Delete a published tweet. Used only to roll back a partial publish."""
        async with self._client() as client:
            resp = await client.delete(
                f"{self._base()}/2/tweets/{urn}", headers=self._headers(acct)
            )
            _raise_for_status(resp)

    @staticmethod
    def _media_id(data: dict[str, Any]) -> str:
        """Extract the media id from a v2 (data.id) or legacy-shaped response."""
        inner = data.get("data") or data
        media_id = inner.get("id") or inner.get("media_id_string")
        if not media_id:
            raise XAPIError(0, "No media id in upload response.")
        return str(media_id)

    async def upload_image(
        self,
        acct: SocialAccount,
        data: bytes,
        *,
        alt: str | None = None,
    ) -> str:
        """Simple (single-request) image upload; returns the media id."""
        headers = self._headers(acct)
        async with self._client() as client:
            resp = await client.post(
                f"{self._base()}/2/media/upload",
                headers=headers,
                data={"media_category": "tweet_image"},
                files={"media": data},
            )
            _raise_for_status(resp)
            media_id = self._media_id(resp.json())
            if alt:
                # Best effort: alt text failing must not fail the upload.
                meta = await client.post(
                    f"{self._base()}/2/media/metadata",
                    headers=headers,
                    json={
                        "id": media_id,
                        "metadata": {"alt_text": {"text": alt[:1000]}},
                    },
                )
                if meta.status_code >= 400:
                    log.warning("x.upload_image.alt_text_failed", media_id=media_id)
        return media_id

    async def upload_video(
        self,
        acct: SocialAccount,
        data: bytes,
    ) -> str:
        """Chunked video upload (INIT / APPEND / FINALIZE); returns the media id.

        FINALIZE may answer with processing_info; the tweet create endpoint
        accepts a still-processing media id and attaches it once ready, so we do
        not poll STATUS here.
        """
        headers = self._headers(acct)
        upload_url = f"{self._base()}/2/media/upload"
        async with self._client() as client:
            init = await client.post(
                upload_url,
                headers=headers,
                data={
                    "command": "INIT",
                    "total_bytes": str(len(data)),
                    "media_type": "video/mp4",
                    "media_category": "tweet_video",
                },
            )
            _raise_for_status(init)
            media_id = self._media_id(init.json())

            for segment, start in enumerate(range(0, len(data), _MEDIA_CHUNK_BYTES)):
                append = await client.post(
                    upload_url,
                    headers=headers,
                    data={
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(segment),
                    },
                    files={"media": data[start : start + _MEDIA_CHUNK_BYTES]},
                )
                _raise_for_status(append)

            finalize = await client.post(
                upload_url,
                headers=headers,
                data={"command": "FINALIZE", "media_id": media_id},
            )
            _raise_for_status(finalize)
        return media_id

    async def refresh(self, acct: SocialAccount) -> dict:
        """Exchange the rotating refresh token for a fresh token set.

        X access tokens live about two hours; offline.access grants a refresh
        token that is single-use and rotated on every refresh, so the caller
        must persist both new tokens immediately.
        """
        if not acct.refresh_token_enc:
            raise XAuthError(401, "No refresh token on account.")
        refresh_token = decrypt(acct.refresh_token_enc)
        async with self._client() as client:
            resp = await client.post(
                f"{self._base()}/2/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.X_CLIENT_ID or "",
                },
                auth=(settings.X_CLIENT_ID or "", settings.X_CLIENT_SECRET or ""),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            # RFC 6749 section 5.2: a dead, revoked, or already-rotated refresh
            # token comes back from the token endpoint as 400 invalid_grant,
            # not 401. Only re-consent can fix it, so surface it as an auth
            # error (mark stale, ask to reconnect) rather than a generic 4xx.
            if resp.status_code == 400:
                raise XAuthError(400, resp.text[:300])
            _raise_for_status(resp)
        return resp.json()

    async def insights(self, acct: SocialAccount, urn: str) -> dict:
        async with self._client() as client:
            resp = await client.get(
                f"{self._base()}/2/tweets/{urn}",
                headers=self._headers(acct),
                params={"tweet.fields": "public_metrics"},
            )
            _raise_for_status(resp)
        return (resp.json().get("data") or {}).get("public_metrics") or {}


x_provider = XProvider()
