"""Idempotent seed: the default writing skill and the bootstrap admin users.

Run with: uv run python -m app.seed

Inserts the default "Super-Hype Post Writer" skill (instructions taken from the
project SKILL.md) and one admin user per entry in BOOTSTRAP_ADMIN_EMAILS. Safe to
re-run: existing rows are left untouched.
"""

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.logger import get_logger
from app.models.user import User
from app.models.writing_skill import WritingSkill

log = get_logger(__name__)

DEFAULT_SKILL_NAME = "Super-Hype Post Writer"
# app/seed.py -> app -> backend -> repo root, where SKILL.md lives.
SKILL_FILE = Path(__file__).resolve().parents[2] / "SKILL.md"


def _parse_skill_file(path: Path) -> tuple[str, str]:
    """Return (description, instructions) parsed from the SKILL.md file.

    The description comes from the YAML frontmatter; the instructions are the
    markdown body after the frontmatter (the actual generation prompt).
    """
    text = path.read_text(encoding="utf-8")
    description = ""
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            frontmatter, body = parts[1], parts[2]
            for line in frontmatter.splitlines():
                if line.lower().startswith("description:"):
                    description = line.split(":", 1)[1].strip()

    return description, body.strip()


async def seed_default_skill(db: AsyncSession) -> None:
    existing = await db.scalar(
        select(WritingSkill).where(WritingSkill.name == DEFAULT_SKILL_NAME)
    )
    if existing is not None:
        log.info("seed.skill.exists", name=DEFAULT_SKILL_NAME)
        return

    if not SKILL_FILE.exists():
        log.warning("seed.skill.file_missing", path=str(SKILL_FILE))
        return

    description, instructions = _parse_skill_file(SKILL_FILE)
    db.add(
        WritingSkill(
            name=DEFAULT_SKILL_NAME,
            description=description or None,
            instructions=instructions,
            is_default=True,
        )
    )
    log.info("seed.skill.created", name=DEFAULT_SKILL_NAME)


async def seed_bootstrap_admins(db: AsyncSession) -> None:
    for email in settings.bootstrap_admin_emails:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is not None:
            log.info("seed.admin.exists", email=email)
            continue
        db.add(User(email=email, role="admin", is_active=True))
        log.info("seed.admin.created", email=email)


async def seed() -> None:
    async with async_session_factory() as db:
        await seed_default_skill(db)
        await seed_bootstrap_admins(db)
        await db.commit()
    log.info("seed.done")


if __name__ == "__main__":
    asyncio.run(seed())
