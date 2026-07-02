"""Post repository: all DB access for campaign posts and interactions."""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post
from app.repositories.base import BaseRepository
from app.schemas.common import Page, PageParams

# A campaign is settled once every post reaches one of these. action_required
# and acknowledged are assisted-manual engagement asks: the automated work is
# done and the ask has been handed to the person, so the campaign should not
# hang in publishing waiting on a human to click "mark done".
_TERMINAL = (
    "published",
    "failed",
    "skipped",
    "action_required",
    "acknowledged",
)


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

    async def list_for_campaign_user(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> list[Post]:
        """A user's posts in one campaign, optionally filtered to given statuses.

        Backs the Slack bundled ask: gather every action a person owns in a
        campaign so one card (and one approve or skip) can settle them together.
        """
        stmt = select(Post).where(
            Post.campaign_id == campaign_id,
            Post.user_id == user_id,
        )
        if statuses is not None:
            stmt = stmt.where(Post.status.in_(statuses))
        stmt = stmt.order_by(Post.created_at, Post.id)
        return list((await db.execute(stmt)).scalars().all())

    async def list_pending_for_campaign_user(
        self, db: AsyncSession, campaign_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[Post]:
        """A user's not-yet-approved posts in one campaign (for readiness checks)."""
        stmt = (
            select(Post)
            .where(
                Post.campaign_id == campaign_id,
                Post.user_id == user_id,
                Post.status.in_(("pending", "scheduled")),
            )
            .order_by(Post.created_at, Post.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def delete_pending_for_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> None:
        """Delete only pending posts (those not yet approved or triggered).

        Used when rebuilding or regenerating a plan. Posts that have been approved
        and are awaiting publish (``scheduled``), already published, failed, or
        skipped are never touched, so editing a plan cannot undo work in flight.
        """
        await db.execute(
            delete(Post).where(
                Post.campaign_id == campaign_id,
                Post.status == "pending",
            )
        )
        await db.flush()

    async def rewind_for_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> int:
        """Rewind every post in a campaign to pending, clearing publish artifacts.

        Used when an admin resets a launched campaign so it can be launched again.
        The plan (rows and their bodies) is kept; only the results of a run are
        wiped: external ids, timestamps, engagement links, per-author media urns,
        errors, and retries. Returns the number of rows reset.
        """
        result = cast(
            CursorResult,
            await db.execute(
                update(Post)
                .where(Post.campaign_id == campaign_id)
                .values(
                    status="pending",
                    external_id=None,
                    published_at=None,
                    scheduled_at=None,
                    first_comment_external_id=None,
                    engagement_url=None,
                    acknowledged_at=None,
                    image_asset_urn=None,
                    error=None,
                    retries=0,
                )
            ),
        )
        await db.flush()
        return result.rowcount

    async def delete_all_for_campaign(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> None:
        """Delete every post for a campaign, regardless of status.

        Used when deleting a whole campaign. The self-referential `target_post_id`
        is resolved within the single statement, so posters and interactions go
        together.
        """
        await db.execute(delete(Post).where(Post.campaign_id == campaign_id))
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

    def _in_window(
        self, stmt: Any, start: datetime | None, end: datetime | None
    ) -> Any:
        """Filter on when the action settled: published_at, else acknowledged_at."""
        completed_at = func.coalesce(Post.published_at, Post.acknowledged_at)
        if start is not None:
            stmt = stmt.where(completed_at >= start)
        if end is not None:
            stmt = stmt.where(completed_at < end)
        return stmt

    async def aggregate_action_counts(
        self,
        db: AsyncSession,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[tuple[uuid.UUID, str, int]]:
        """Return (user_id, action, count) for completed actions in the window.

        Reposts and posts only count when published; likes and comments also count
        when acknowledged (assisted-manual). Grouped so scoring stays in the
        service, and bounded to one row per (user, action).
        """
        published_only = Post.action.in_(("repost_comment", "post"))
        status_ok = or_(
            Post.status == "published",
            (Post.status == "acknowledged") & (~published_only),
        )
        stmt = (
            select(Post.user_id, Post.action, func.count())
            .where(status_ok)
            .group_by(Post.user_id, Post.action)
        )
        stmt = self._in_window(stmt, start, end)
        rows = await db.execute(stmt)
        return [(r[0], r[1], r[2]) for r in rows]

    async def aggregate_direct_posts(
        self,
        db: AsyncSession,
        *,
        brand_keywords: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[tuple[uuid.UUID, int, int]]:
        """Return (user_id, brand_text_posts, brand_media_posts) per user.

        A published direct post counts toward the brand bonus when its body or
        native body mentions a brand keyword. It counts as a media post when an
        image is attached (our proxy for the text+video tier), otherwise as a
        text post. Non-brand posts are excluded entirely.
        """
        if not brand_keywords:
            return []

        # Join with a space so a keyword can never be matched across the seam
        # between the two bodies (for example body ending "TF" + native "Y").
        text = func.lower(
            func.coalesce(Post.body, "") + " " + func.coalesce(Post.body_native, "")
        )
        brand_match = or_(*[text.contains(kw) for kw in brand_keywords])
        has_media = or_(
            Post.image_asset_id.is_not(None),
            Post.image_url.is_not(None),
            Post.image_asset_urn.is_not(None),
        )
        media_count = func.sum(case((has_media, 1), else_=0))
        text_count = func.sum(case((has_media, 0), else_=1))

        stmt = (
            select(Post.user_id, text_count, media_count)
            .where(
                Post.action == "post",
                Post.status == "published",
                brand_match,
            )
            .group_by(Post.user_id)
        )
        stmt = self._in_window(stmt, start, end)
        rows = await db.execute(stmt)
        return [(r[0], int(r[1] or 0), int(r[2] or 0)) for r in rows]

    async def all_terminal(self, db: AsyncSession, campaign_id: uuid.UUID) -> bool:
        """True if the campaign has posts and every one is settled (see _TERMINAL)."""
        stmt = select(Post.status).where(Post.campaign_id == campaign_id)
        statuses = [row[0] for row in (await db.execute(stmt)).all()]
        return bool(statuses) and all(s in _TERMINAL for s in statuses)


post_repo = PostRepository()
