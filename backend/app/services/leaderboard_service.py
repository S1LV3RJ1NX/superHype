"""Leaderboard scoring.

Ranks members by a weighted score of the amplification actions super-hype
recorded for them (likes, bookmarks, comments, reposts) plus a bonus for direct
posts that mention the brand. The score is cross-platform: X and LinkedIn
actions share the same action names and are aggregated together, so one blended
ranking covers both. Bookmarks are X only (LinkedIn has no save API), so a
LinkedIn member simply never earns that term. Impressions have no member-post
API, so that term stays 0 for now and is kept only as a seam for a future
analytics source.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.post_repo import post_repo

# Scoring weights. Kept here so the formula lives in one place. A bookmark (X
# only) is a save: stronger intent than a like, lighter than a comment. On X it
# rides along with a like, so a bookmarking member earns like + bookmark for the
# same approval, which is the intended cross-platform edge for X activity.
LIKE_WEIGHT = 1
BOOKMARK_WEIGHT = 2
COMMENT_WEIGHT = 3
REPOST_WEIGHT = 5
IMPRESSION_DIVISOR = 1000
BRAND_TEXT_BONUS = 10
BRAND_MEDIA_BONUS = 30


@dataclass
class MemberScore:
    user_id: uuid.UUID
    likes: int = 0
    bookmarks: int = 0
    comments: int = 0
    reposts: int = 0
    direct_posts: int = 0
    brand_posts: int = 0
    impressions: int = 0
    score: int = field(default=0)


async def compute_scores(
    db: AsyncSession,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[MemberScore]:
    """Return per-member scores (unranked) for everyone with activity in window."""
    counts = await post_repo.aggregate_action_counts(db, start=start, end=end)
    brand = await post_repo.aggregate_direct_posts(
        db, brand_keywords=settings.brand_keywords, start=start, end=end
    )

    rows: dict[uuid.UUID, MemberScore] = {}

    def _row(user_id: uuid.UUID) -> MemberScore:
        row = rows.get(user_id)
        if row is None:
            row = MemberScore(user_id=user_id)
            rows[user_id] = row
        return row

    for user_id, action, count in counts:
        row = _row(user_id)
        if action == "like":
            row.likes = count
        elif action == "bookmark":
            row.bookmarks = count
        elif action == "comment":
            row.comments = count
        elif action == "repost_comment":
            row.reposts = count
        elif action == "post":
            row.direct_posts = count

    brand_bonus: dict[uuid.UUID, int] = {}
    for user_id, text_posts, media_posts in brand:
        row = _row(user_id)
        row.brand_posts = text_posts + media_posts
        brand_bonus[user_id] = (
            text_posts * BRAND_TEXT_BONUS + media_posts * BRAND_MEDIA_BONUS
        )

    for user_id, row in rows.items():
        row.score = (
            row.likes * LIKE_WEIGHT
            + row.bookmarks * BOOKMARK_WEIGHT
            + row.comments * COMMENT_WEIGHT
            + row.reposts * REPOST_WEIGHT
            + row.impressions // IMPRESSION_DIVISOR
            + brand_bonus.get(user_id, 0)
        )

    return list(rows.values())
