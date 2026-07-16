"""Provider Protocol and shared error hierarchy for social-platform publishing.

Concrete providers (LinkedIn, X) implement this Protocol and raise these error
types, so the worker's retry policy (auth -> reconnect, 429 -> delayed retry,
other 4xx -> fail fast, 5xx -> bounded backoff) is written once and works for
every platform.
"""

from typing import Protocol, runtime_checkable

from app.models.social_account import SocialAccount


class ProviderAPIError(Exception):
    """A provider API call failed for a non-auth, non-rate-limit reason.

    Subclasses set ``status_code``. ``duplicate_external_id`` carries the
    already-live post id when the platform rejected the call as duplicate
    content and named the existing post (LinkedIn does; X does not), so the
    worker can adopt it instead of failing a post that is in fact live.
    """

    status_code: int = 0
    duplicate_external_id: str | None = None


class ProviderAuthError(ProviderAPIError):
    """401: the token is invalid or revoked. Non-retryable; mark the account stale."""


class ProviderRateLimitError(ProviderAPIError):
    """429: throttled. Retryable after retry_after seconds."""

    retry_after: int | None = None


@runtime_checkable
class Provider(Protocol):
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
        """Publish a post and return the post URN."""
        ...

    async def upload_image(
        self,
        acct: SocialAccount,
        data: bytes,
        *,
        alt: str | None = None,
    ) -> str:
        """Upload an image and return urn:li:image owned by acct."""
        ...

    async def upload_video(
        self,
        acct: SocialAccount,
        data: bytes,
    ) -> str:
        """Upload a video and return urn:li:video owned by acct."""
        ...

    async def comment(
        self,
        acct: SocialAccount,
        target_urn: str,
        text: str,
    ) -> str:
        """Post a comment on target_urn and return the comment URN."""
        ...

    async def like(
        self,
        acct: SocialAccount,
        target_urn: str,
    ) -> None:
        """Like the target post."""
        ...

    async def bookmark(
        self,
        acct: SocialAccount,
        target_urn: str,
    ) -> None:
        """Bookmark/save the target post (X only)."""
        ...

    async def reshare(
        self,
        acct: SocialAccount,
        target_urn: str,
        commentary: str = "",
    ) -> str:
        """Reshare target_urn with optional commentary; return the new post id."""
        ...

    async def delete_post(self, acct: SocialAccount, urn: str) -> None:
        """Delete a published post (rollback of a partial publish)."""
        ...

    async def refresh(self, acct: SocialAccount) -> dict:
        """Refresh tokens and return the new set."""
        ...

    async def insights(self, acct: SocialAccount, urn: str) -> dict:
        """Fetch engagement insights (not implemented in v1)."""
        ...
