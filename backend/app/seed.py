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

# The starting org teams and their default personas (voice guidance injected
# into generated comments and reshares). The migration seeds the names too; this
# keeps local DB resets (and any env where the data migration was skipped) in
# sync, and fills a default persona for teams that do not have one yet.
DEFAULT_TEAMS: list[tuple[str, str]] = [
    (
        "Founders",
        "A founder voice: direct, high-conviction, and outcome-focused. Talks "
        "about the problem and the bet behind it, not features. Comfortable with "
        "a strong opinion and a real question.",
    ),
    (
        "Founder's Office",
        "Operates across the company: connects strategy to execution, cites "
        "concrete metrics or milestones, and frames things in terms of leverage "
        "and priorities.",
    ),
    (
        "GTM",
        "A go-to-market voice: customer and pipeline oriented, speaks to buyer "
        "pain, use cases, and outcomes in the field, grounded and practical.",
    ),
    (
        "Marketing and Sales",
        "A marketing and sales voice: crisp positioning, a clear hook, and value "
        "framed for the reader. Persuasive without hype or buzzwords.",
    ),
    (
        "Engineering",
        "An engineer's voice: precise and technical, curious about how it works, "
        "trade-offs, and real-world constraints. Skeptical of marketing spin.",
    ),
    (
        "EO/FDE",
        "A forward-deployed engineer voice: hands-on with customers, pragmatic "
        "about what actually ships, and specific about the technical detail that "
        "matters.",
    ),
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
    for name, persona in DEFAULT_TEAMS:
        existing = await db.scalar(select(Team).where(Team.name == name))
        if existing is not None:
            # Backfill a persona for teams seeded before personas existed.
            if not existing.persona:
                existing.persona = persona
                log.info("seed.team.persona_backfilled", name=name)
            else:
                log.info("seed.team.exists", name=name)
            continue
        db.add(Team(name=name, is_active=True, persona=persona))
        log.info("seed.team.created", name=name)


async def seed() -> None:
    async with async_session_factory() as db:
        await seed_bootstrap_admins(db)
        await seed_default_teams(db)
        await db.commit()
    log.info("seed.done")


if __name__ == "__main__":
    asyncio.run(seed())
