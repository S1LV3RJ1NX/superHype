"""Repository for SocialAccount (LinkedIn connections)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.social_account import SocialAccount
from app.repositories.base import BaseRepository


class SocialAccountRepository(BaseRepository[SocialAccount]):
    model = SocialAccount

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        platform: str = "linkedin",
    ) -> SocialAccount | None:
        stmt = select(SocialAccount).where(
            SocialAccount.user_id == user_id,
            SocialAccount.platform == platform,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        platform: str,
        external_urn: str,
        display_name: str,
        access_token_enc: bytes,
        refresh_token_enc: bytes | None,
        scopes: list[str] | None,
        expires_at: datetime | None,
        status: str = "active",
    ) -> SocialAccount:
        existing = await self.get_by_user(db, user_id, platform)
        if existing is not None:
            existing.external_urn = external_urn
            existing.display_name = display_name
            existing.access_token_enc = access_token_enc
            existing.refresh_token_enc = refresh_token_enc
            existing.scopes = scopes
            existing.expires_at = expires_at
            existing.status = status
            await db.flush()
            return existing

        account = SocialAccount(
            user_id=user_id,
            platform=platform,
            external_urn=external_urn,
            display_name=display_name,
            access_token_enc=access_token_enc,
            refresh_token_enc=refresh_token_enc,
            scopes=scopes,
            expires_at=expires_at,
            status=status,
        )
        db.add(account)
        await db.flush()
        return account

    async def mark_stale(self, db: AsyncSession, account_id: uuid.UUID) -> None:
        account = await self.get(db, account_id)
        if account is not None:
            account.status = "stale"
            await db.flush()


social_account_repo = SocialAccountRepository()
