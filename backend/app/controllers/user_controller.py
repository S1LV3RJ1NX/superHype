"""User controller: listing and role management with audit logging."""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories import audit_repo
from app.repositories.user_repo import user_repo
from app.schemas.common import Page, PageParams
from app.schemas.user import UserOut


async def list_users(db: AsyncSession, params: PageParams) -> Page[UserOut]:
    page = await user_repo.paginate(db, params=params)
    return Page[UserOut](
        items=[UserOut.model_validate(u) for u in page.items],
        next_cursor=page.next_cursor,
    )


async def get_me(db: AsyncSession, user: User) -> UserOut:
    return UserOut.model_validate(user)


async def change_role(
    db: AsyncSession,
    *,
    target_id: uuid.UUID,
    new_role: str,
    actor: User,
) -> UserOut:
    target = await user_repo.get(db, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    old_role = target.role
    if old_role == new_role:
        return UserOut.model_validate(target)

    if old_role == "admin" and new_role != "admin":
        admin_count = await user_repo.count_admins(db)
        if admin_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot demote the last admin.",
            )

    await user_repo.set_role(db, target, new_role)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="role_change",
        detail={
            "target_id": str(target.id),
            "old_role": old_role,
            "new_role": new_role,
        },
    )
    await db.commit()
    await db.refresh(target)
    return UserOut.model_validate(target)
