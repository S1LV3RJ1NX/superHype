"""Provider Protocol for social-platform publishing.

The concrete LinkedIn implementation lands in Phase 4 alongside the
campaign worker. This Protocol defines the interface so the rest of the
codebase can type-check against it.
"""

from typing import Protocol, runtime_checkable

from app.models.social_account import SocialAccount


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

    async def refresh(self, acct: SocialAccount) -> dict:
        """Refresh tokens and return the new set."""
        ...

    async def insights(self, acct: SocialAccount, urn: str) -> dict:
        """Fetch engagement insights (not implemented in v1)."""
        ...
