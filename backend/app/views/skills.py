"""Writing-skill endpoints: CRUD, archive, publish, test, and set-default."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import skill_controller
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Page, PageParams
from app.schemas.skill import (
    GenerateInstructionsRequest,
    GenerateInstructionsResponse,
    SkillCreate,
    SkillOut,
    SkillTestRequest,
    SkillTestResponse,
    SkillUpdate,
)

router = APIRouter(prefix="/v1/skills", tags=["skills"])


@router.get("", response_model=Page[SkillOut])
async def list_skills(
    include_archived: bool = False,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Page[SkillOut]:
    return await skill_controller.list_skills(
        db, params=params, include_archived=include_archived
    )


@router.get("/{skill_id}", response_model=SkillOut)
async def get_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SkillOut:
    return await skill_controller.get_skill(db, skill_id)


@router.post("", response_model=SkillOut, status_code=201)
async def create_skill(
    body: SkillCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> SkillOut:
    return await skill_controller.create_skill(db, body, actor)


@router.patch("/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> SkillOut:
    return await skill_controller.update_skill(db, skill_id, body, actor)


@router.delete("/{skill_id}", status_code=204)
async def archive_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> None:
    await skill_controller.archive_skill(db, skill_id, actor)


@router.post("/generate-instructions", response_model=GenerateInstructionsResponse)
async def generate_instructions(
    body: GenerateInstructionsRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> GenerateInstructionsResponse:
    text = await skill_controller.generate_instructions_ctrl(db, body, actor)
    return GenerateInstructionsResponse(instructions=text)


@router.post("/{skill_id}/test", response_model=SkillTestResponse)
async def test_skill(
    skill_id: uuid.UUID,
    body: SkillTestRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> SkillTestResponse:
    output = await skill_controller.test_skill(db, skill_id, body, actor)
    return SkillTestResponse(output=output)


@router.post("/{skill_id}/publish", response_model=SkillOut)
async def publish_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> SkillOut:
    return await skill_controller.publish_skill(db, skill_id, actor)


@router.post("/{skill_id}/set-default", response_model=SkillOut)
async def set_default(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("editor")),
) -> SkillOut:
    return await skill_controller.set_default(db, skill_id, actor)
