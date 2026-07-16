"""LinkedIn provider: publish, image upload, comment, like, reshare, token refresh.

Uses the versioned /rest API with httpx. Tokens are decrypted only here, never
logged. Errors are typed so the worker can decide retry behavior: auth (stale,
non-retryable), rate limit (retryable with delay), or a generic API error.
"""

import re
from typing import Any
from urllib.parse import quote

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

_REST_BASE = "https://api.linkedin.com/rest"
_OAUTH_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_TIMEOUT = httpx.Timeout(30.0)

# When identical content was already posted (common after a reset and relaunch),
# LinkedIn rejects with 422 "Content is a duplicate of urn:li:share:..." and
# names the live URN; we extract it so the worker can adopt it as published.
_DUPLICATE_URN_RE = re.compile(r"urn:li:(?:share|ugcPost|activity):\d+")


class LinkedInAPIError(ProviderAPIError):
    """A LinkedIn API call failed for a non-auth, non-rate-limit reason."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        if status_code == 422 and "duplicate" in message.lower():
            match = _DUPLICATE_URN_RE.search(message)
            self.duplicate_external_id = match.group(0) if match else None
        super().__init__(f"LinkedIn API error {status_code}: {message}")


class LinkedInAuthError(LinkedInAPIError, ProviderAuthError):
    """401: the token is invalid or revoked. Non-retryable; mark the account stale."""


class LinkedInRateLimitError(LinkedInAPIError, ProviderRateLimitError):
    """429: throttled. Retryable after retry_after seconds."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(429, message)


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    body = resp.text[:300]
    if resp.status_code == 401:
        raise LinkedInAuthError(401, body)
    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after")
        raise LinkedInRateLimitError(
            body, int(retry_after) if retry_after and retry_after.isdigit() else None
        )
    raise LinkedInAPIError(resp.status_code, body)


class LinkedInProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # transport is injectable so tests can route calls through a MockTransport.
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport)

    def _headers(self, acct: SocialAccount) -> dict[str, str]:
        token = decrypt(acct.access_token_enc)
        return {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": settings.LINKEDIN_API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

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
        commentary = text
        if link and link_in_body:
            commentary = f"{text}\n\n{link}".strip()

        payload: dict[str, Any] = {
            "author": acct.external_urn,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if image_urn:
            payload["content"] = {"media": {"id": image_urn}}
        if reshare_of:
            payload["reshareContext"] = {"parent": reshare_of}

        async with self._client() as client:
            resp = await client.post(
                f"{_REST_BASE}/posts", headers=self._headers(acct), json=payload
            )
            _raise_for_status(resp)
        urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id")
        if not urn:
            raise LinkedInAPIError(resp.status_code, "No post URN in response headers.")
        return urn

    async def upload_image(
        self,
        acct: SocialAccount,
        data: bytes,
        *,
        alt: str | None = None,
    ) -> str:
        headers = self._headers(acct)
        async with self._client() as client:
            init = await client.post(
                f"{_REST_BASE}/images?action=initializeUpload",
                headers=headers,
                json={"initializeUploadRequest": {"owner": acct.external_urn}},
            )
            _raise_for_status(init)
            value = init.json()["value"]
            upload_url = value["uploadUrl"]
            image_urn = value["image"]

            put = await client.put(
                upload_url,
                headers={"Authorization": headers["Authorization"]},
                content=data,
            )
            _raise_for_status(put)
        return image_urn

    async def upload_video(
        self,
        acct: SocialAccount,
        data: bytes,
    ) -> str:
        """Upload a short video via the chunked Videos API; returns urn:li:video.

        LinkedIn returns one or more byte-range upload instructions; we PUT each
        chunk, collect the ETag part ids, then finalize. Short campaign clips are
        usually a single part, but the loop handles a multi-part split too.
        """
        headers = self._headers(acct)
        async with self._client() as client:
            init = await client.post(
                f"{_REST_BASE}/videos?action=initializeUpload",
                headers=headers,
                json={
                    "initializeUploadRequest": {
                        "owner": acct.external_urn,
                        "fileSizeBytes": len(data),
                        "uploadCaptions": False,
                        "uploadThumbnail": False,
                    }
                },
            )
            _raise_for_status(init)
            value = init.json()["value"]
            video_urn = value["video"]
            upload_token = value.get("uploadToken", "")
            instructions = value.get("uploadInstructions", [])

            part_ids: list[str] = []
            for instr in instructions:
                first = int(instr["firstByte"])
                last = int(instr["lastByte"])
                put = await client.put(
                    instr["uploadUrl"],
                    headers={"Authorization": headers["Authorization"]},
                    content=data[first : last + 1],
                )
                _raise_for_status(put)
                etag = put.headers.get("etag")
                if etag:
                    part_ids.append(etag)

            finalize = await client.post(
                f"{_REST_BASE}/videos?action=finalizeUpload",
                headers=headers,
                json={
                    "finalizeUploadRequest": {
                        "video": video_urn,
                        "uploadToken": upload_token,
                        "uploadedPartIds": part_ids,
                    }
                },
            )
            _raise_for_status(finalize)
        return video_urn

    async def delete_post(self, acct: SocialAccount, urn: str) -> None:
        """Delete a published post. Used only to roll back a partial publish."""
        encoded = quote(urn, safe="")
        async with self._client() as client:
            resp = await client.delete(
                f"{_REST_BASE}/posts/{encoded}", headers=self._headers(acct)
            )
            _raise_for_status(resp)

    async def comment(
        self,
        acct: SocialAccount,
        target_urn: str,
        text: str,
    ) -> str:
        encoded = quote(target_urn, safe="")
        payload = {
            "actor": acct.external_urn,
            "object": target_urn,
            "message": {"text": text},
        }
        async with self._client() as client:
            resp = await client.post(
                f"{_REST_BASE}/socialActions/{encoded}/comments",
                headers=self._headers(acct),
                json=payload,
            )
            _raise_for_status(resp)
        return resp.headers.get("x-restli-id") or resp.json().get("$URN", "")

    async def like(
        self,
        acct: SocialAccount,
        target_urn: str,
    ) -> None:
        encoded = quote(target_urn, safe="")
        payload = {"actor": acct.external_urn, "object": target_urn}
        async with self._client() as client:
            resp = await client.post(
                f"{_REST_BASE}/socialActions/{encoded}/likes",
                headers=self._headers(acct),
                json=payload,
            )
            _raise_for_status(resp)

    async def bookmark(
        self,
        acct: SocialAccount,
        target_urn: str,
    ) -> None:
        # LinkedIn has no save/bookmark API; the planner never creates bookmark
        # rows for LinkedIn campaigns, so reaching this is a plan-building bug.
        raise LinkedInAPIError(400, "LinkedIn does not support bookmarks.")

    async def reshare(
        self,
        acct: SocialAccount,
        target_urn: str,
        commentary: str = "",
    ) -> str:
        """Reshare target_urn with optional commentary; returns the new post URN."""
        return await self.publish(acct, commentary, reshare_of=target_urn)

    async def refresh(self, acct: SocialAccount) -> dict:
        if not acct.refresh_token_enc:
            raise LinkedInAuthError(401, "No refresh token on account.")
        refresh_token = decrypt(acct.refresh_token_enc)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.LINKEDIN_CLIENT_ID,
            "client_secret": settings.LINKEDIN_CLIENT_SECRET,
        }
        async with self._client() as client:
            resp = await client.post(_OAUTH_TOKEN_URL, data=form)
            # RFC 6749 section 5.2: a dead or revoked refresh token comes back
            # from the token endpoint as 400 invalid_grant, not 401. Only
            # re-consent can fix it, so surface it as an auth error.
            if resp.status_code == 400:
                raise LinkedInAuthError(400, resp.text[:300])
            _raise_for_status(resp)
        return resp.json()

    async def insights(self, acct: SocialAccount, urn: str) -> dict:
        raise NotImplementedError("Insights are not implemented in v1.")


linkedin_provider = LinkedInProvider()
