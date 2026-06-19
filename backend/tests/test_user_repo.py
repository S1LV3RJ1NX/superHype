"""Tests for the user repository."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user_repo import user_repo


async def test_get_by_email(db: AsyncSession):
    user = User(
        id=uuid.uuid4(),
        email="repo@test.local",
        name="Repo",
        role="viewer",
        is_active=True,
    )
    db.add(user)
    await db.commit()

    found = await user_repo.get_by_email(db, "repo@test.local")
    assert found is not None
    assert found.email == "repo@test.local"

    found_upper = await user_repo.get_by_email(db, "REPO@TEST.LOCAL")
    assert found_upper is not None


async def test_get_by_email_returns_none(db: AsyncSession):
    found = await user_repo.get_by_email(db, "missing@test.local")
    assert found is None


async def test_count_admins(db: AsyncSession):
    assert await user_repo.count_admins(db) == 0

    for i in range(3):
        db.add(
            User(
                id=uuid.uuid4(),
                email=f"admin{i}@test.local",
                role="admin",
                is_active=True,
            )
        )
    db.add(
        User(
            id=uuid.uuid4(),
            email="viewer@test.local",
            role="viewer",
            is_active=True,
        )
    )
    await db.commit()

    assert await user_repo.count_admins(db) == 3


async def test_set_role(db: AsyncSession):
    user = User(
        id=uuid.uuid4(),
        email="rolechange@test.local",
        name="RC",
        role="viewer",
        is_active=True,
    )
    db.add(user)
    await db.commit()

    await user_repo.set_role(db, user, "editor")
    await db.commit()
    await db.refresh(user)
    assert user.role == "editor"
