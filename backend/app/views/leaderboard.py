"""Leaderboard route: ranked super-hyper scores, any authed user."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import leaderboard_controller
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.leaderboard import LeaderboardOut

router = APIRouter(prefix="/v1/leaderboard", tags=["leaderboard"])


@router.get("", response_model=LeaderboardOut)
async def get_leaderboard(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LeaderboardOut:
    """Ranked members by contribution score. Omit start/end for all-time."""
    return await leaderboard_controller.get_leaderboard(
        db, start=start, end=end, limit=limit
    )
