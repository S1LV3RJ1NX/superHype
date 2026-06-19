"""Tests for the writing_skill_repo."""

import pytest

from app.models.writing_skill import WritingSkill
from app.repositories.writing_skill_repo import writing_skill_repo


@pytest.mark.asyncio
async def test_get_default_returns_default(db):
    skill = WritingSkill(name="Default", instructions="inst", is_default=True)
    db.add(skill)
    await db.commit()

    result = await writing_skill_repo.get_default(db)
    assert result is not None
    assert result.name == "Default"


@pytest.mark.asyncio
async def test_get_default_returns_none_when_no_default(db):
    result = await writing_skill_repo.get_default(db)
    assert result is None


@pytest.mark.asyncio
async def test_list_active_excludes_archived(db):
    db.add(WritingSkill(name="Active", instructions="i1", is_default=True))
    db.add(WritingSkill(name="Archived", instructions="i2", is_archived=True))
    await db.commit()

    active = await writing_skill_repo.list_active(db)
    names = [s.name for s in active]
    assert "Active" in names
    assert "Archived" not in names


@pytest.mark.asyncio
async def test_list_active_default_first(db):
    db.add(WritingSkill(name="Beta", instructions="i1"))
    db.add(WritingSkill(name="Alpha", instructions="i2", is_default=True))
    await db.commit()

    active = await writing_skill_repo.list_active(db)
    assert active[0].is_default is True
    assert active[0].name == "Alpha"


@pytest.mark.asyncio
async def test_set_default_clears_previous(db):
    s1 = WritingSkill(name="S1", instructions="i1", is_default=True)
    s2 = WritingSkill(name="S2", instructions="i2")
    db.add(s1)
    db.add(s2)
    await db.commit()

    await writing_skill_repo.set_default(db, s2)
    await db.commit()
    await db.refresh(s1)
    await db.refresh(s2)

    assert s1.is_default is False
    assert s2.is_default is True
