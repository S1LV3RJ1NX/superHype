"""Post repository: all DB access for campaign posts and interactions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.repositories.base import BaseRepository
from app.schemas.common import Page, PageParams

_TERMINAL = ("published", "failed", "skipped")


class PostRepository(BaseRepository[Post]):
    model = Post

    async def paginate_for_campaign(
        self, db: AsyncSession, *, params: PageParams, campaign_id: uuid.UUID
    ) -> Page[Post]:
        return await self.paginate(db, params=params, campaign_id=campaign_id)

    async def list_for_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> list[Post]:
        stmt = (
            select(Post)
            .where(Post.campaign_id == campaign_id)
            .order_by(Post.created_at, Post.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def list_pending_for_user(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> list[Post]:
        stmt = (
            select(Post)
            .where(
                Post.user_id == user_id,
                Post.status.in_(("pending", "scheduled")),
            )
            .order_by(Post.created_at, Post.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def delete_unlocked_for_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> None:
        """Delete posts that are still editable (not approved/published/skipped).

        Used when rebuilding or regenerating a plan; approved or published work is
        never touched.
        """
        await db.execute(
            delete(Post).where(
                Post.campaign_id == campaign_id,
                Post.status.in_(("pending", "scheduled")),
            )
        )
        await db.flush()

    async def mark_published(
        self, db: AsyncSession, post: Post, external_id: str
    ) -> Post:
        post.external_id = external_id
        post.status = "published"
        post.published_at = datetime.now(UTC)
        await db.flush()
        return post

    async def mark_failed(self, db: AsyncSession, post: Post, error: str) -> Post:
        post.status = "failed"
        post.error = error
        await db.flush()
        return post

    async def bulk_create(self, db: AsyncSession, posts: list[Post]) -> list[Post]:
        db.add_all(posts)
        await db.flush()
        return posts

    async def published_times_for_account(
        self, db: AsyncSession, account_id: uuid.UUID, since: datetime
    ) -> list[datetime]:
        """Published_at timestamps for an account since `since`, across campaigns.

        Backs the per-account daily cap and min-spacing guardrails. Filtering by
        `since` happens in Python so naive/aware timestamps from SQLite in tests
        compare cleanly; the row count per account is naturally bounded.
        """
        stmt = select(Post.published_at).where(
            Post.social_account_id == account_id,
            Post.published_at.is_not(None),
        )
        out: list[datetime] = []
        for (ts,) in (await db.execute(stmt)).all():
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts >= since:
                out.append(ts)
        return out

    async def all_terminal(self, db: AsyncSession, campaign_id: uuid.UUID) -> bool:
        """True if the campaign has posts and every one is in a terminal state."""
        stmt = select(Post.status).where(Post.campaign_id == campaign_id)
        statuses = [row[0] for row in (await db.execute(stmt)).all()]
        return bool(statuses) and all(s in _TERMINAL for s in statuses)


post_repo = PostRepository()
