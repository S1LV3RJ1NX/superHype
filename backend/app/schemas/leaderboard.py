"""Leaderboard response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: uuid.UUID
    name: str | None
    avatar_url: str | None
    team_name: str | None
    likes: int
    bookmarks: int
    comments: int
    reposts: int
    direct_posts: int
    brand_posts: int
    impressions: int
    score: int


class LeaderboardOut(BaseModel):
    start: datetime | None
    end: datetime | None
    entries: list[LeaderboardEntry]
