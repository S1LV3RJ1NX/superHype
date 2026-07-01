"""Team controller: listing for everyone, create/update for admins, with audit."""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team
from app.models.user import User
from app.repositories import audit_repo
from app.repositories.team_repo import team_repo
from app.schemas.common import Page, PageParams
from app.schemas.team import TeamOut, TeamUpdate


def _hydrate(teams: list[Team], counts: dict[uuid.UUID, int]) -> list[TeamOut]:
    out: list[TeamOut] = []
    for team in teams:
        item = TeamOut.model_validate(team)
        item.member_count = counts.get(team.id, 0)
        out.append(item)
    return out


async def list_teams(db: AsyncSession, params: PageParams) -> Page[TeamOut]:
    """Active teams, newest first, for onboarding, profile, and the planner."""
    page = await team_repo.paginate(db, params=params, is_active=True)
    counts = await team_repo.member_counts(db, [t.id for t in page.items])
    return Page[TeamOut](
        items=_hydrate(page.items, counts), next_cursor=page.next_cursor
    )


async def list_all_teams(db: AsyncSession, params: PageParams) -> Page[TeamOut]:
    """Every team including archived ones (admin management view)."""
    page = await team_repo.paginate(db, params=params)
    counts = await team_repo.member_counts(db, [t.id for t in page.items])
    return Page[TeamOut](
        items=_hydrate(page.items, counts), next_cursor=page.next_cursor
    )


async def create_team(db: AsyncSession, *, name: str, actor: User) -> TeamOut:
    name = name.strip()
    existing = await team_repo.get_by_name(db, name)
    if existing is not None:
        raise HTTPException(status_code=409, detail="A team with that name exists.")
    team = await team_repo.create(db, name=name, is_active=True)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="team_created",
        detail={"team_id": str(team.id), "name": name},
    )
    await db.commit()
    return TeamOut.model_validate(team)


async def update_team(
    db: AsyncSession, *, team_id: uuid.UUID, body: TeamUpdate, actor: User
) -> TeamOut:
    team = await team_repo.get(db, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found.")

    fields: dict[str, object] = {}
    if body.name is not None:
        new_name = body.name.strip()
        if new_name.lower() != team.name.lower():
            clash = await team_repo.get_by_name(db, new_name)
            if clash is not None:
                raise HTTPException(
                    status_code=409, detail="A team with that name exists."
                )
        fields["name"] = new_name
    if body.is_active is not None:
        fields["is_active"] = body.is_active

    if not fields:
        counts = await team_repo.member_counts(db, [team.id])
        out = TeamOut.model_validate(team)
        out.member_count = counts.get(team.id, 0)
        return out

    await team_repo.update(db, team, **fields)
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action="team_updated",
        detail={"team_id": str(team.id), **{k: str(v) for k, v in fields.items()}},
    )
    await db.commit()
    counts = await team_repo.member_counts(db, [team.id])
    out = TeamOut.model_validate(team)
    out.member_count = counts.get(team.id, 0)
    return out
