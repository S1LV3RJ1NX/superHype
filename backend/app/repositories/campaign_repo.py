"""Campaign repository: DB access for campaigns and pagination."""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign
from app.models.post import Post
from app.repositories.base import BaseRepository
from app.schemas.common import Page, PageParams, encode_cursor


class CampaignRepository(BaseRepository[Campaign]):
    model = Campaign

    async def list_by_status(self, db: AsyncSession, status: str) -> list[Campaign]:
        """All campaigns in a given status (used by the reconciliation poll).

        The publishing set is naturally small (only launched, not-yet-settled
        campaigns), so this is bounded without pagination.
        """
        stmt = select(Campaign).where(Campaign.status == status)
        return list((await db.execute(stmt)).scalars().all())

    async def find_scheduled_between(
        self,
        db: AsyncSession,
        start: datetime,
        end: datetime,
        *,
        exclude_id: uuid.UUID | None = None,
        exclude_statuses: tuple[str, ...] = ("failed",),
    ) -> list[Campaign]:
        """Campaigns whose scheduled_at falls in [start, end).

        Used both for the one-per-day conflict check (with a day-wide range and an
        exclude) and for the events-calendar feed (a month-wide range). Failed
        campaigns are excluded by default so a dead schedule never blocks a day.
        """
        stmt = select(Campaign).where(
            Campaign.scheduled_at.is_not(None),
            Campaign.scheduled_at >= start,
            Campaign.scheduled_at < end,
        )
        if exclude_id is not None:
            stmt = stmt.where(Campaign.id != exclude_id)
        if exclude_statuses:
            stmt = stmt.where(Campaign.status.not_in(exclude_statuses))
        stmt = stmt.order_by(Campaign.scheduled_at.asc())
        return list((await db.execute(stmt)).scalars().all())

    async def find_due_for_launch(
        self, db: AsyncSession, now: datetime
    ) -> list[Campaign]:
        """Scheduled campaigns whose time has arrived and are not yet launched.

        Due-ness is read from Postgres, never from Redis-deferred jobs, so a
        restarted worker sees everything that came due while it was down.
        """
        stmt = (
            select(Campaign)
            .where(
                Campaign.scheduled_at.is_not(None),
                Campaign.scheduled_at <= now,
                Campaign.launched_at.is_(None),
            )
            .order_by(Campaign.scheduled_at.asc())
        )
        return list((await db.execute(stmt)).scalars().all())

    async def find_stamped_unlaunched(
        self, db: AsyncSession, since: datetime
    ) -> list[Campaign]:
        """Campaigns stamped launched recently but still sitting in review.

        A crash between the launch stamp (committed) and enqueuing launch_campaign
        leaves this state. The poller re-enqueues with the fixed _job_id, a no-op
        if the job already exists.
        """
        stmt = select(Campaign).where(
            Campaign.launched_at.is_not(None),
            Campaign.launched_at >= since,
            Campaign.status == "review",
        )
        return list((await db.execute(stmt)).scalars().all())

    async def stamp_launched_if_unlaunched(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        *,
        launched_by: uuid.UUID | None,
        now: datetime,
    ) -> bool:
        """Conditionally stamp launched_at/launched_by; return True if we won.

        A conditional write (WHERE launched_at IS NULL) so a second poll tick or a
        second worker replica loses the race and skips, guaranteeing no campaign
        is launched twice.
        """
        stmt = (
            update(Campaign)
            .where(Campaign.id == campaign_id, Campaign.launched_at.is_(None))
            .values(launched_at=now, launched_by=launched_by)
        )
        result = cast("CursorResult[Any]", await db.execute(stmt))
        return (result.rowcount or 0) > 0

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
