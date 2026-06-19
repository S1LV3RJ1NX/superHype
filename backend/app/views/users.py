"""Users routes: me, list, and role management (admin only)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers import user_controller
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Page, PageParams
from app.schemas.user import RoleUpdate, UserOut

router = APIRouter(prefix="/v1/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    return await user_controller.get_me(db, user)


@router.get("", response_model=Page[UserOut])
async def list_users(
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
) -> Page[UserOut]:
    return await user_controller.list_users(db, params)


@router.patch("/{user_id}", response_model=UserOut)
async def change_role(
    user_id: uuid.UUID,
    body: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("admin")),
) -> UserOut:
    return await user_controller.change_role(
        db, target_id=user_id, new_role=body.role, actor=actor
    )
