"""User controller: listing, role management, and self-service team selection."""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories import audit_repo
from app.repositories.social_account_repo import social_account_repo
from app.repositories.team_repo import team_repo
from app.repositories.user_repo import user_repo
from app.schemas.common import Page, PageParams
from app.schemas.user import UserOut


async def _hydrate_one(db: AsyncSession, user: User) -> UserOut:
    out = UserOut.model_validate(user)
    status_map = await social_account_repo.map_status_for_users(db, [user.id])
    out.linkedin_status = status_map.get(user.id)
    x_map = await social_account_repo.map_status_for_users(db, [user.id], platform="x")
    out.x_status = x_map.get(user.id)
    if user.team_id is not None:
        names = await team_repo.names_for(db, [user.team_id])
        out.team_name = names.get(user.team_id)
    return out


async def list_users(
    db: AsyncSession, params: PageParams, search: str | None = None
) -> Page[UserOut]:
    page = await user_repo.paginate_search(db, params=params, search=search)
    user_ids = [u.id for u in page.items]
    status_map = await social_account_repo.map_status_for_users(db, user_ids)
    x_map = await social_account_repo.map_status_for_users(db, user_ids, platform="x")
    team_ids = [u.team_id for u in page.items if u.team_id is not None]
    name_map = await team_repo.names_for(db, team_ids)
    items = []
    for u in page.items:
        out = UserOut.model_validate(u)
        out.linkedin_status = status_map.get(u.id)
        out.x_status = x_map.get(u.id)
        if u.team_id is not None:
            out.team_name = name_map.get(u.team_id)
        items.append(out)
    return Page[UserOut](items=items, next_cursor=page.next_cursor)


async def get_me(db: AsyncSession, user: User) -> UserOut:
    # Re-load so the response always reflects the latest persisted state (e.g. a
    # team just set), independent of how the authenticated user was resolved.
    fresh = await user_repo.get(db, user.id)
    return await _hydrate_one(db, fresh or user)


async def set_my_team(db: AsyncSession, *, user: User, team_id: uuid.UUID) -> UserOut:
    """Self-service team selection: powers onboarding and the profile page."""
    team = await team_repo.get(db, team_id)
    if team is None or not team.is_active:
        raise HTTPException(status_code=404, detail="Team not found.")

    # Re-load within this session so the update persists regardless of where the
    # authenticated user object came from.
    target = await user_repo.get(db, user.id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if target.team_id != team.id:
        await user_repo.update(db, target, team_id=team.id)
        await audit_repo.record(
            db,
            actor_id=target.id,
            action="team_assigned",
            detail={"team_id": str(team.id), "name": team.name},
        )
        # No role change on team selection: everyone joins as a viewer and an
        # admin grants editor manually via PATCH /v1/users/{id}.
        await db.commit()
    return await _hydrate_one(db, target)


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
        return await _hydrate_one(db, target)

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
    return await _hydrate_one(db, target)
