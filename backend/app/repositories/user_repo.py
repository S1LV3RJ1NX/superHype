"""User repository: all database access for the users aggregate."""

import uuid

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository
from app.schemas.common import Page, PageParams, encode_cursor


class UserRepository(BaseRepository[User]):
    model = User

    async def paginate_search(
        self, db: AsyncSession, *, params: PageParams, search: str | None = None
    ) -> Page[User]:
        """Keyset paginate users, optionally filtered by a name/email/role match.

        Same (created_at, id) keyset scheme as the base paginate, but adds a
        case-insensitive substring filter so the admin search covers every user,
        not just the current page.
        """
        stmt = select(User)
        if search:
            like = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.name.ilike(like),
                    User.email.ilike(like),
                    User.role.ilike(like),
                )
            )

        cursor = params.decoded_cursor
        if cursor is not None:
            created_at, row_id = cursor
            stmt = stmt.where(tuple_(User.created_at, User.id) < (created_at, row_id))

        stmt = stmt.order_by(User.created_at.desc(), User.id.desc()).limit(
            params.limit + 1
        )

        result = await db.execute(stmt)
        rows = list(result.scalars().all())

        next_cursor: str | None = None
        if len(rows) > params.limit:
            rows = rows[: params.limit]
            last = rows[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return Page[User](items=rows, next_cursor=next_cursor)

    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_ids(self, db: AsyncSession, ids: list[uuid.UUID]) -> list[User]:
        if not ids:
            return []
        stmt = select(User).where(User.id.in_(ids))
        return list((await db.execute(stmt)).scalars().all())

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
