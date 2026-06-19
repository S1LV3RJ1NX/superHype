"""User repository: all database access for the users aggregate."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_google_sub(self, db: AsyncSession, google_sub: str) -> User | None:
        stmt = select(User).where(User.google_sub == google_sub)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def count_admins(self, db: AsyncSession) -> int:
        stmt = select(func.count()).select_from(User).where(User.role == "admin")
        result = await db.execute(stmt)
        return result.scalar_one()

    async def set_role(self, db: AsyncSession, user: User, role: str) -> User:
        return await self.update(db, user, role=role)


user_repo = UserRepository()
