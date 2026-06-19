"""Campaign repository: DB access for campaigns and pagination."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign
from app.models.post import Post
from app.repositories.base import BaseRepository
from app.schemas.common import Page, PageParams, encode_cursor


class CampaignRepository(BaseRepository[Campaign]):
    model = Campaign

    async def set_status(
        self, db: AsyncSession, campaign: Campaign, status: str
    ) -> Campaign:
        campaign.status = status
        await db.flush()
        return campaign

    async def count_by_status(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> dict[str, int]:
        stmt = (
            select(Post.status, func.count())
            .where(Post.campaign_id == campaign_id)
            .group_by(Post.status)
        )
        return {row[0]: row[1] for row in (await db.execute(stmt)).all()}

    async def paginate_for_user(
        self,
        db: AsyncSession,
        *,
        params: PageParams,
        user_id: uuid.UUID,
        is_admin: bool,
    ) -> Page[Campaign]:
        """Keyset page of campaigns visible to the user.

        Admins see all; everyone else sees campaigns they created or participate in
        (have a post in). Keyset on (created_at, id), newest first.
        """
        stmt = select(Campaign)
        if not is_admin:
            participant = select(Post.campaign_id).where(Post.user_id == user_id)
            stmt = stmt.where(
                (Campaign.created_by == user_id) | (Campaign.id.in_(participant))
            )

        cursor = params.decoded_cursor
        if cursor is not None:
            created_at, row_id = cursor
            stmt = stmt.where(
                (Campaign.created_at < created_at)
                | ((Campaign.created_at == created_at) & (Campaign.id < row_id))
            )

        stmt = stmt.order_by(Campaign.created_at.desc(), Campaign.id.desc()).limit(
            params.limit + 1
        )
        rows = list((await db.execute(stmt)).scalars().all())

        next_cursor: str | None = None
        if len(rows) > params.limit:
            rows = rows[: params.limit]
            last = rows[-1]
            next_cursor = encode_cursor(last.created_at, last.id)
        return Page[Campaign](items=rows, next_cursor=next_cursor)


campaign_repo = CampaignRepository()
