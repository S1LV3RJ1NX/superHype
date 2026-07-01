"""Team repository: all database access for the teams aggregate."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team
from app.models.user import User
from app.repositories.base import BaseRepository


class TeamRepository(BaseRepository[Team]):
    model = Team

    async def list_active(self, db: AsyncSession) -> list[Team]:
        stmt = select(Team).where(Team.is_active.is_(True)).order_by(Team.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, db: AsyncSession, name: str) -> Team | None:
        stmt = select(Team).where(func.lower(Team.name) == name.lower())
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def names_for(
        self, db: AsyncSession, team_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        """Return {team_id: name} for the given teams (for hydrating users)."""
        ids = [tid for tid in team_ids if tid is not None]
        if not ids:
            return {}
        stmt = select(Team.id, Team.name).where(Team.id.in_(ids))
        result = await db.execute(stmt)
        return {row[0]: row[1] for row in result}

    async def member_counts(
        self, db: AsyncSession, team_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Return {team_id: member_count} for the given teams."""
        if not team_ids:
            return {}
        stmt = (
            select(User.team_id, func.count())
            .where(User.team_id.in_(team_ids))
            .group_by(User.team_id)
        )
        result = await db.execute(stmt)
        return {row[0]: row[1] for row in result if row[0] is not None}


team_repo = TeamRepository()
