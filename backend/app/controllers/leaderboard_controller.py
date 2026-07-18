"""Leaderboard controller: score, hydrate identity, rank, and cap the list."""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.team_repo import team_repo
from app.repositories.user_repo import user_repo
from app.schemas.leaderboard import LeaderboardEntry, LeaderboardOut
from app.services import leaderboard_service


async def get_leaderboard(
    db: AsyncSession,
    *,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> LeaderboardOut:
    scores = await leaderboard_service.compute_scores(db, start=start, end=end)
    # A leaderboard only ranks people who actually earned points; drop the noise
    # of members whose recorded actions net to zero (for example a lone non-brand
    # direct post, which contributes nothing to the score).
    scores = [s for s in scores if s.score > 0]

    users = await user_repo.list_by_ids(db, [s.user_id for s in scores])
    user_map = {u.id: u for u in users}
    team_ids = [u.team_id for u in users if u.team_id is not None]
    team_names = await team_repo.names_for(db, team_ids)

    def _name(user_id: uuid.UUID) -> str:
        u = user_map.get(user_id)
        return (u.name or u.email) if u else ""

    # Highest score first; stable tiebreak by display name so ranks are consistent.
    scores.sort(key=lambda s: (-s.score, _name(s.user_id).lower()))

    entries: list[LeaderboardEntry] = []
    for rank, s in enumerate(scores[:limit], start=1):
        u = user_map.get(s.user_id)
        entries.append(
            LeaderboardEntry(
                rank=rank,
                user_id=s.user_id,
                name=u.name if u else None,
                avatar_url=u.avatar_url if u else None,
                team_name=team_names.get(u.team_id) if u and u.team_id else None,
                likes=s.likes,
                bookmarks=s.bookmarks,
                comments=s.comments,
                reposts=s.reposts,
                direct_posts=s.direct_posts,
                brand_posts=s.brand_posts,
                impressions=s.impressions,
                score=s.score,
            )
        )

    return LeaderboardOut(start=start, end=end, entries=entries)
