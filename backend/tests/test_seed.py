from sqlalchemy import select

from app import seed
from app.models.writing_skill import WritingSkill

SKILL_CONTENT = """---
name: super-hype-posts
description: A concise description.
---

# Super-Hype Post Writer

The body of the prompt.
"""


async def test_seed_default_skill_is_idempotent(db, monkeypatch, tmp_path):
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(SKILL_CONTENT, encoding="utf-8")
    monkeypatch.setattr(seed, "SKILL_FILE", skill_file)

    await seed.seed_default_skill(db)
    await db.flush()
    await seed.seed_default_skill(db)
    await db.flush()

    rows = (await db.execute(select(WritingSkill))).scalars().all()
    assert len(rows) == 1
    skill = rows[0]
    assert skill.name == "Super-Hype Post Writer"
    assert skill.is_default is True
    assert skill.is_seed is True
    assert skill.status == "published"
    assert skill.description == "A concise description."
    assert "The body of the prompt." in skill.instructions
    assert "super-hype-posts" not in skill.instructions
