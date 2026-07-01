"""Teams routes: list for any authed user; create/update for admins."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import team_controller
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Page, PageParams
from app.schemas.team import TeamCreate, TeamOut, TeamUpdate

router = APIRouter(prefix="/v1/teams", tags=["teams"])


@router.get("", response_model=Page[TeamOut])
async def list_teams(
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Page[TeamOut]:
    """Active teams, for onboarding, profile, and the campaign planner."""
    return await team_controller.list_teams(db, params)


@router.get("/all", response_model=Page[TeamOut])
async def list_all_teams(
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
) -> Page[TeamOut]:
    """Every team including archived ones (admin management view)."""
    return await team_controller.list_all_teams(db, params)


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(
    body: TeamCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("admin")),
) -> TeamOut:
    return await team_controller.create_team(
        db, name=body.name, persona=body.persona, actor=actor
    )


@router.patch("/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: uuid.UUID,
    body: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("admin")),
) -> TeamOut:
    return await team_controller.update_team(
        db, team_id=team_id, body=body, actor=actor
    )
