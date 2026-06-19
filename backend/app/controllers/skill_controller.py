"""Controller for writing-skill management with audit logging."""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.user import User
from app.models.writing_skill import WritingSkill
from app.repositories import audit_repo
from app.repositories.writing_skill_repo import writing_skill_repo
from app.schemas.common import Page, PageParams
from app.schemas.generation import GenerationBrief, RosterEntry
from app.schemas.skill import (
    GenerateInstructionsRequest,
    SkillCreate,
    SkillOut,
    SkillTestRequest,
    SkillUpdate,
)
from app.services.generation_service import (
    GenerationError,
    draft_instructions,
    generate,
)

log = get_logger(__name__)


async def list_skills(
    db: AsyncSession, *, params: PageParams, include_archived: bool = False
) -> Page[SkillOut]:
    if include_archived:
        page = await writing_skill_repo.paginate(db, params=params)
    else:
        page = await writing_skill_repo.list_active_page(db, params=params)
    return Page[SkillOut](
        items=[SkillOut.model_validate(s) for s in page.items],
        next_cursor=page.next_cursor,
    )


async def get_skill(db: AsyncSession, skill_id: uuid.UUID) -> SkillOut:
    skill = await writing_skill_repo.get(db, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found.")
    return SkillOut.model_validate(skill)


async def create_skill(db: AsyncSession, body: SkillCreate, actor: User) -> SkillOut:
    skill = await writing_skill_repo.create(
        db,
        name=body.name,
        description=body.description,
        instructions=body.instructions,
        created_by=actor.id,
        status="draft",
    )
    await audit_repo.record(
        db, actor_id=actor.id, action="skill_created", detail={"name": body.name}
    )
    await db.commit()
    await db.refresh(skill)
    return SkillOut.model_validate(skill)


def _guard_seed(skill: WritingSkill, action: str) -> None:
    if skill.is_seed:
        raise HTTPException(403, f"Cannot {action} the seed skill.")


async def update_skill(
    db: AsyncSession, skill_id: uuid.UUID, body: SkillUpdate, actor: User
) -> SkillOut:
    skill = await writing_skill_repo.get(db, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found.")
    _guard_seed(skill, "update")

    updates = body.model_dump(exclude_unset=True)
    if updates:
        await writing_skill_repo.update(db, skill, **updates)
        await audit_repo.record(
            db,
            actor_id=actor.id,
            action="skill_updated",
            detail={"skill_id": str(skill_id), **updates},
        )
        await db.commit()
        await db.refresh(skill)
    return SkillOut.model_validate(skill)


async def archive_skill(db: AsyncSession, skill_id: uuid.UUID, actor: User) -> None:
    skill = await writing_skill_repo.get(db, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found.")
    _guard_seed(skill, "archive")
    if skill.is_default:
        raise HTTPException(
            409, "Cannot archive the default skill. Set another default first."
        )
    await writing_skill_repo.archive(db, skill)
    await audit_repo.record(
        db, actor_id=actor.id, action="skill_archived", detail={"name": skill.name}
    )
    await db.commit()


async def publish_skill(db: AsyncSession, skill_id: uuid.UUID, actor: User) -> SkillOut:
    skill = await writing_skill_repo.get(db, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found.")
    _guard_seed(skill, "publish")
    if skill.status == "published":
        raise HTTPException(400, "Skill is already published.")
    await writing_skill_repo.publish(db, skill)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="skill_published",
        detail={"skill_id": str(skill_id), "name": skill.name},
    )
    await db.commit()
    await db.refresh(skill)
    return SkillOut.model_validate(skill)


async def test_skill(
    db: AsyncSession, skill_id: uuid.UUID, body: SkillTestRequest, actor: User
) -> dict:
    """Run a sample generation with the skill to preview output."""
    skill = await writing_skill_repo.get(db, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found.")

    brief = GenerationBrief(
        title=body.title,
        raw_brief=body.raw_brief,
        roster=[RosterEntry(name="Alex", role="Engineer")],
    )

    try:
        result = await generate(skill, brief)
    except GenerationError as exc:
        log.error("test_skill.generation_error", error=str(exc))
        raise HTTPException(
            502, "Test generation failed. The skill may produce invalid output."
        ) from exc

    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="skill_tested",
        detail={"skill_id": str(skill_id), "title": body.title},
    )
    await db.commit()
    return result.model_dump()


async def generate_instructions_ctrl(
    db: AsyncSession, body: GenerateInstructionsRequest, actor: User
) -> str:
    """Controller wrapper: call the generation service and handle errors."""
    try:
        text = await draft_instructions(body.description)
    except GenerationError as exc:
        log.error("generate_instructions.error", error=str(exc))
        raise HTTPException(
            502, "Instruction generation failed. Please try again."
        ) from exc

    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="skill_instructions_generated",
        detail={"description": body.description[:200]},
    )
    await db.commit()
    return text


async def set_default(db: AsyncSession, skill_id: uuid.UUID, actor: User) -> SkillOut:
    skill = await writing_skill_repo.get(db, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found.")
    if skill.is_archived:
        raise HTTPException(400, "Cannot set an archived skill as default.")
    if skill.status == "draft":
        raise HTTPException(400, "Cannot set a draft skill as default. Publish first.")
    await writing_skill_repo.set_default(db, skill)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="skill_set_default",
        detail={"skill_id": str(skill_id), "name": skill.name},
    )
    await db.commit()
    await db.refresh(skill)
    return SkillOut.model_validate(skill)
