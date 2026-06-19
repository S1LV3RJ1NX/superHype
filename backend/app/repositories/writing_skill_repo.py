"""Repository for WritingSkill (the swappable generation profile)."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.writing_skill import WritingSkill
from app.repositories.base import BaseRepository
from app.schemas.common import Page, PageParams


class WritingSkillRepository(BaseRepository[WritingSkill]):
    model = WritingSkill

    async def get_default(self, db: AsyncSession) -> WritingSkill | None:
        stmt = select(WritingSkill).where(WritingSkill.is_default.is_(True))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_page(
        self, db: AsyncSession, *, params: PageParams
    ) -> Page[WritingSkill]:
        """Paginated active skills using the base keyset (created_at, id)."""
        return await self.paginate(db, params=params, is_archived=False)

    async def list_active(self, db: AsyncSession) -> list[WritingSkill]:
        stmt = (
            select(WritingSkill)
            .where(WritingSkill.is_archived.is_(False))
            .order_by(WritingSkill.is_default.desc(), WritingSkill.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def archive(self, db: AsyncSession, skill: WritingSkill) -> WritingSkill:
        skill.is_archived = True
        await db.flush()
        return skill

    async def publish(self, db: AsyncSession, skill: WritingSkill) -> WritingSkill:
        skill.status = "published"
        await db.flush()
        return skill

    async def set_default(self, db: AsyncSession, skill: WritingSkill) -> WritingSkill:
        await db.execute(
            update(WritingSkill)
            .where(WritingSkill.is_default.is_(True))
            .values(is_default=False)
        )
        skill.is_default = True
        await db.flush()
        return skill


writing_skill_repo = WritingSkillRepository()
