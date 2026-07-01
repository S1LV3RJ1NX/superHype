"""Idempotent seed: the bootstrap admin users and the default teams.

Run with: uv run python -m app.seed

Inserts one admin user per entry in BOOTSTRAP_ADMIN_EMAILS and the default org
teams. Safe to re-run: existing rows are left untouched.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.logger import get_logger
from app.models.team import Team
from app.models.user import User

log = get_logger(__name__)

# The starting org teams. The migration seeds these too; this keeps local DB
# resets (and any env where the data migration was skipped) in sync.
DEFAULT_TEAMS = [
    "Founders",
    "Founder's Office",
    "GTM",
    "Marketing and Sales",
    "Engineering",
    "EO/FDE",
]


async def seed_bootstrap_admins(db: AsyncSession) -> None:
    for email in settings.bootstrap_admin_emails:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is not None:
            log.info("seed.admin.exists", email=email)
            continue
        db.add(User(email=email, role="admin", is_active=True))
        log.info("seed.admin.created", email=email)


async def seed_default_teams(db: AsyncSession) -> None:
    for name in DEFAULT_TEAMS:
        existing = await db.scalar(select(Team).where(Team.name == name))
        if existing is not None:
            log.info("seed.team.exists", name=name)
            continue
        db.add(Team(name=name, is_active=True))
        log.info("seed.team.created", name=name)


async def seed() -> None:
    async with async_session_factory() as db:
        await seed_bootstrap_admins(db)
        await seed_default_teams(db)
        await db.commit()
    log.info("seed.done")


if __name__ == "__main__":
    asyncio.run(seed())
