"""Opt-in auto-approve: the MANUAL_APPROVAL_ONLY flag, consent, and the worker.

With the flag on (the default) every action waits for its owner and consent
cannot be recorded. With it off, a person who opted in has their scheduled
actions approved when the review window closes, unless they skipped them first.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.workers.jobs as jobs_mod
from app.config import settings
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.user import User

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple] = []
        self.kv: dict = {}

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))

    async def get(self, key):
        return self.kv.get(key)


@pytest_asyncio.fixture
async def env(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_mod, "async_session_factory", maker)
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: None)
    redis = _FakeRedis()
    return {"maker": maker, "ctx": {"redis": redis}, "redis": redis}


@pytest.fixture
def auto_mode(monkeypatch):
    monkeypatch.setattr(settings, "MANUAL_APPROVAL_ONLY", False)


async def _user(db, *, consented: bool) -> User:
    u = User(
        email=f"{uuid.uuid4().hex}@corp.com",
        role="editor",
        is_active=True,
        auto_approve_consented_at=datetime.now(UTC) if consented else None,
    )
    db.add(u)
    await db.flush()
    return u


async def _campaign_with_posts(db, user, *, status="pending", n=2) -> Campaign:
    c = Campaign(
        title="C",
        type="amplify",
        status="publishing",
        launched_at=datetime.now(UTC),
    )
    db.add(c)
    await db.flush()
    for _ in range(n):
        db.add(
            Post(
                campaign_id=c.id,
                user_id=user.id,
                action="like",
                status=status,
                target_external_id="urn:li:activity:1",
                idempotency_key=uuid.uuid4().hex,
            )
        )
    await db.commit()
    return c


def _auto_jobs(redis):
    return [j for j in redis.jobs if j[0] == "auto_approve_posts"]


# --- Consent endpoint ---------------------------------------------------------


async def test_opt_in_refused_while_manual_only(client: AsyncClient, as_role):
    async with as_role("viewer"):
        me = await client.get("/v1/users/me")
        resp = await client.put("/v1/users/me/auto-approve", json={"enabled": True})
    assert me.json()["auto_approve_available"] is False
    assert resp.status_code == 409


async def test_opt_in_and_out_record_consent_and_audit(
    client: AsyncClient, as_role, engine, auto_mode
):
    async with as_role("viewer") as user:
        on = await client.put("/v1/users/me/auto-approve", json={"enabled": True})
        off = await client.put("/v1/users/me/auto-approve", json={"enabled": False})
        actor_id = user.id
    assert on.status_code == 200
    assert on.json()["auto_approve_available"] is True
    assert on.json()["auto_approve_consented_at"] is not None
    assert off.json()["auto_approve_consented_at"] is None

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        actions = (
            (
                await s.execute(
                    select(AuditLog.action).where(AuditLog.actor_id == actor_id)
                )
            )
            .scalars()
            .all()
        )
    assert "auto_approve_opt_in" in actions
    assert "auto_approve_opt_out" in actions


async def test_opt_out_always_allowed_while_manual_only(client: AsyncClient, as_role):
    async with as_role("viewer"):
        resp = await client.put("/v1/users/me/auto-approve", json={"enabled": False})
    assert resp.status_code == 200


# --- Worker -------------------------------------------------------------------


async def test_notify_schedules_auto_approve_for_consenting_user(db, env, auto_mode):
    user = await _user(db, consented=True)
    c = await _campaign_with_posts(db, user)

    await jobs_mod.notify_participant(env["ctx"], str(c.id), str(user.id))

    jobs = _auto_jobs(env["redis"])
    assert len(jobs) == 1
    assert jobs[0][2]["_defer_by"] == settings.AUTO_APPROVE_DELAY_SECONDS
    assert jobs[0][2]["_job_id"] == f"auto:{c.id}:{user.id}"


async def test_manual_only_flag_ignores_existing_consent(db, env):
    user = await _user(db, consented=True)
    c = await _campaign_with_posts(db, user)

    await jobs_mod.notify_participant(env["ctx"], str(c.id), str(user.id))

    assert _auto_jobs(env["redis"]) == []


async def test_no_auto_approve_without_consent(db, env, auto_mode):
    user = await _user(db, consented=False)
    c = await _campaign_with_posts(db, user)

    await jobs_mod.notify_participant(env["ctx"], str(c.id), str(user.id))

    assert _auto_jobs(env["redis"]) == []


async def test_auto_approve_approves_scheduled_but_not_skipped(db, env, auto_mode):
    user = await _user(db, consented=True)
    c = await _campaign_with_posts(db, user, status="scheduled")
    skipped = Post(
        campaign_id=c.id,
        user_id=user.id,
        action="like",
        status="skipped",
        target_external_id="urn:li:activity:2",
        idempotency_key=uuid.uuid4().hex,
    )
    db.add(skipped)
    await db.commit()

    await jobs_mod.auto_approve_posts(env["ctx"], str(c.id), str(user.id))

    async with env["maker"]() as s:
        rows = (
            (await s.execute(select(Post).where(Post.campaign_id == c.id)))
            .scalars()
            .all()
        )
        statuses = sorted(r.status for r in rows)
        audit = (
            (
                await s.execute(
                    select(AuditLog.action).where(AuditLog.campaign_id == c.id)
                )
            )
            .scalars()
            .all()
        )
    assert statuses == ["approved", "approved", "skipped"]
    assert audit.count("post_auto_approved") == 2
    published = [j for j in env["redis"].jobs if j[0] == "publish_post"]
    assert len(published) == 2


async def test_auto_approve_noop_after_opt_out(db, env, auto_mode):
    user = await _user(db, consented=False)
    c = await _campaign_with_posts(db, user, status="scheduled")

    await jobs_mod.auto_approve_posts(env["ctx"], str(c.id), str(user.id))

    async with env["maker"]() as s:
        rows = (await s.execute(select(Post))).scalars().all()
    assert {r.status for r in rows} == {"scheduled"}
    assert not [j for j in env["redis"].jobs if j[0] == "publish_post"]


async def test_auto_approve_noop_when_flag_back_on(db, env):
    user = await _user(db, consented=True)
    c = await _campaign_with_posts(db, user, status="scheduled")

    await jobs_mod.auto_approve_posts(env["ctx"], str(c.id), str(user.id))

    async with env["maker"]() as s:
        rows = (await s.execute(select(Post))).scalars().all()
    assert {r.status for r in rows} == {"scheduled"}


async def test_auto_approve_noop_when_paused(db, env, auto_mode):
    user = await _user(db, consented=True)
    c = await _campaign_with_posts(db, user, status="scheduled")
    async with env["maker"]() as s:
        await s.execute(
            update(Campaign).where(Campaign.id == c.id).values(status="paused")
        )
        await s.commit()

    await jobs_mod.auto_approve_posts(env["ctx"], str(c.id), str(user.id))

    async with env["maker"]() as s:
        rows = (await s.execute(select(Post))).scalars().all()
    assert {r.status for r in rows} == {"scheduled"}


async def test_resume_reschedules_auto_approve(db, env, auto_mode):
    user = await _user(db, consented=True)
    c = await _campaign_with_posts(db, user, status="scheduled")

    await jobs_mod.resume_campaign(env["ctx"], str(c.id))

    assert len(_auto_jobs(env["redis"])) == 1


async def test_reconcile_requeues_lost_auto_approve(db, env, auto_mode):
    user = await _user(db, consented=True)
    c = await _campaign_with_posts(db, user, status="scheduled")
    overdue = datetime.now(UTC) - timedelta(
        seconds=settings.AUTO_APPROVE_DELAY_SECONDS
        + settings.RECONCILE_STALLED_SECONDS
        + 60
    )
    async with env["maker"]() as s:
        await s.execute(
            update(Post).where(Post.campaign_id == c.id).values(updated_at=overdue)
        )
        await s.commit()

    await jobs_mod.reconcile_campaigns(env["ctx"])

    jobs = _auto_jobs(env["redis"])
    assert len(jobs) == 1
    assert jobs[0][2]["_job_id"] == f"auto:{c.id}:{user.id}"
