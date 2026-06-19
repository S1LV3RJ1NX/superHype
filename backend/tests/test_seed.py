from sqlalchemy import select

from app import seed
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
