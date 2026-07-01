"""Structural test: verify the Provider Protocol is runtime-checkable."""

from app.models.social_account import SocialAccount
from app.providers.base import Provider


class DummyProvider:
    """Minimal implementation satisfying the Provider Protocol."""

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
        return "urn:li:share:1"

    async def upload_image(
        self,
        acct: SocialAccount,
        data: bytes,
        *,
        alt: str | None = None,
    ) -> str:
        return "urn:li:image:1"

    async def upload_video(self, acct: SocialAccount, data: bytes) -> str:
        return "urn:li:video:1"

    async def comment(self, acct: SocialAccount, target_urn: str, text: str) -> str:
        return "urn:li:comment:1"

    async def like(self, acct: SocialAccount, target_urn: str) -> None:
        return None

    async def refresh(self, acct: SocialAccount) -> object:
        return {}

    async def insights(self, acct: SocialAccount, urn: str) -> dict:
        return {}


def test_dummy_satisfies_provider_protocol():
    assert isinstance(DummyProvider(), Provider)
