from sqlalchemy import select

from app import seed
from app.models.team import Team
from app.models.user import User


async def test_seed_bootstrap_admins_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(
        type(seed.settings),
        "bootstrap_admin_emails",
        property(lambda self: ["admin@corp.com", "boss@corp.com"]),
    )

    await seed.seed_bootstrap_admins(db)
    await db.flush()
    await seed.seed_bootstrap_admins(db)
    await db.flush()

    rows = (await db.execute(select(User))).scalars().all()
    emails = sorted(u.email for u in rows)
    assert emails == ["admin@corp.com", "boss@corp.com"]
    assert all(u.role == "admin" for u in rows)


async def test_seed_default_teams_creates_teams_with_persona(db):
    await seed.seed_default_teams(db)
    await db.flush()

    rows = {t.name: t for t in (await db.execute(select(Team))).scalars().all()}
    for name, persona in seed.DEFAULT_TEAMS:
        assert name in rows
        assert rows[name].persona == persona
        assert rows[name].is_active is True


async def test_seed_default_teams_backfills_missing_persona(db):
    # A team seeded before personas existed: persona is NULL.
    name, expected = seed.DEFAULT_TEAMS[0]
    db.add(Team(name=name, is_active=True, persona=None))
    await db.flush()

    await seed.seed_default_teams(db)
    await db.flush()

    team = await db.scalar(select(Team).where(Team.name == name))
    assert team is not None
    assert team.persona == expected


async def test_seed_default_teams_preserves_custom_persona(db):
    # An admin-edited persona must not be clobbered by re-seeding.
    name = seed.DEFAULT_TEAMS[0][0]
    db.add(Team(name=name, is_active=True, persona="custom voice"))
    await db.flush()

    await seed.seed_default_teams(db)
    await db.flush()

    team = await db.scalar(select(Team).where(Team.name == name))
    assert team is not None
    assert team.persona == "custom voice"


async def test_seed_default_teams_is_idempotent(db):
    await seed.seed_default_teams(db)
    await db.flush()
    await seed.seed_default_teams(db)
    await db.flush()

    rows = (await db.execute(select(Team))).scalars().all()
    names = sorted(t.name for t in rows)
    assert names == sorted(name for name, _ in seed.DEFAULT_TEAMS)
