"""Fail-safe reconciliation: the publish single-flight lease and the reconcile cron.

The lease is exercised directly against the repo and through publish_post; the
cron is exercised against the job with a fake Redis and a stub provider, mirroring
test_worker_jobs.py. Together they prove a re-driven publish never double-posts
and that work stranded by a lost job is recovered from Postgres.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.workers.jobs as jobs_mod
from app.config import settings
from app.core.crypto import encrypt
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.models.user import User
from app.providers.linkedin import LinkedInRateLimitError
from app.repositories.post_repo import post_repo

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple] = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))


class _StubProvider:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def publish(self, acct, text, **kw):
        self.calls.append(("publish", text, kw))
        return "urn:li:share:new"

    async def comment(self, acct, target_urn, text):
        self.calls.append(("comment", target_urn, text))
        return "urn:li:comment:new"

    async def like(self, acct, target_urn):
        self.calls.append(("like", target_urn))

    async def reshare(self, acct, target_urn, text=""):
        self.calls.append(("reshare", target_urn, text))
        return "urn:li:share:re"

    async def upload_image(self, acct, data, alt=None):
        self.calls.append(("upload_image", len(data)))
        return "urn:li:image:1"

    async def upload_video(self, acct, data):
        self.calls.append(("upload_video", len(data)))
        return "urn:li:video:1"

    async def delete_post(self, acct, urn):
        self.calls.append(("delete_post", urn))


@pytest_asyncio.fixture
async def env(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_mod, "async_session_factory", maker)
    redis = _FakeRedis()
    provider = _StubProvider()
    monkeypatch.setattr(jobs_mod, "_provider", lambda platform="linkedin": provider)
    return {
        "maker": maker,
        "ctx": {"redis": redis},
        "redis": redis,
        "provider": provider,
    }


@pytest.fixture
def cm_enabled(monkeypatch):
    monkeypatch.setattr(settings, "COMMUNITY_MANAGEMENT_ENABLED", True)


async def _user(db) -> User:
    u = User(email=f"{uuid.uuid4().hex}@corp.com", role="editor", is_active=True)
    db.add(u)
    await db.flush()
    return u


async def _account(db, user) -> SocialAccount:
    acct = SocialAccount(
        user_id=user.id,
        platform="linkedin",
        external_urn="urn:li:person:x",
        display_name="T",
        access_token_enc=encrypt("tok"),
        refresh_token_enc=None,
        scopes=["w_member_social"],
        status="active",
    )
    db.add(acct)
    await db.flush()
    return acct


async def _set_updated_at(maker, post_id: uuid.UUID, when: datetime) -> None:
    """Force a row's updated_at (explicit value skips the onupdate bump)."""
    async with maker() as s:
        await s.execute(update(Post).where(Post.id == post_id).values(updated_at=when))
        await s.commit()


# --- Publish single-flight lease ---------------------------------------------


async def test_lease_concurrent_acquire_loses(db, env):
    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        action="like",
        status="approved",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()

    now = datetime.now(UTC)
    async with env["maker"]() as s:
        won_a = await post_repo.try_acquire_publish_lease(
            s, p.id, now=now, ttl_seconds=600
        )
        await s.commit()
    async with env["maker"]() as s:
        won_b = await post_repo.try_acquire_publish_lease(
            s, p.id, now=now, ttl_seconds=600
        )
        await s.commit()
    assert won_a is True
    assert won_b is False


async def test_lease_expired_is_reclaimable(db, env):
    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        action="like",
        status="approved",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()

    now = datetime.now(UTC)
    # A lease taken 700s ago with a 600s TTL is expired.
    async with env["maker"]() as s:
        await post_repo.try_acquire_publish_lease(
            s, p.id, now=now - timedelta(seconds=700), ttl_seconds=600
        )
        await s.commit()
    async with env["maker"]() as s:
        won = await post_repo.try_acquire_publish_lease(
            s, p.id, now=now, ttl_seconds=600
        )
        await s.commit()
    assert won is True


async def test_lease_released_can_be_reacquired(db, env):
    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        action="like",
        status="approved",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()

    now = datetime.now(UTC)
    async with env["maker"]() as s:
        assert await post_repo.try_acquire_publish_lease(
            s, p.id, now=now, ttl_seconds=600
        )
        await s.commit()
    async with env["maker"]() as s:
        await post_repo.release_publish_lease(s, p.id)
        await s.commit()
    # After release the (unexpired-by-time) lease is free again immediately.
    async with env["maker"]() as s:
        assert await post_repo.try_acquire_publish_lease(
            s, p.id, now=now, ttl_seconds=600
        )
        await s.commit()


async def test_publish_with_held_lease_defers_without_posting(db, env, cm_enabled):
    # Another worker holds the lease: publish_post must not touch the provider; it
    # re-enqueues itself shortly instead of dropping the work.
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="like",
        status="approved",
        target_external_id="urn:li:activity:1",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()
    # Simulate a live lease held by another run.
    async with env["maker"]() as s:
        await s.execute(
            update(Post)
            .where(Post.id == p.id)
            .values(publish_leased_until=datetime.now(UTC) + timedelta(seconds=300))
        )
        await s.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert env["provider"].calls == []
    deferred = [j for j in env["redis"].jobs if j[0] == "publish_post"]
    assert len(deferred) == 1
    assert deferred[0][2]["_defer_by"] == jobs_mod._LEASE_CONTENTION_DEFER_SECONDS
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "approved"


async def test_lease_released_after_successful_publish(db, env, cm_enabled):
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="like",
        status="approved",
        target_external_id="urn:li:activity:1",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "published"
        assert rp.publish_leased_until is None


async def test_lease_released_after_failed_publish(db, env, cm_enabled):
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="like",
        status="approved",
        target_external_id="urn:li:activity:1",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()

    async def _throttle(*a, **k):
        raise LinkedInRateLimitError("slow down", retry_after=42)

    env["provider"].like = _throttle

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        # Re-enqueued for retry, and the lease is freed so the retry can re-acquire.
        assert rp.status == "approved"
        assert rp.publish_leased_until is None
    assert [j for j in env["redis"].jobs if j[0] == "publish_post"]


# --- reconcile_campaigns cron ------------------------------------------------


async def test_reconcile_stale_approved_reenqueued(db, env):
    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        action="like",
        status="approved",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()
    # Idle well past the stalled threshold: its publish_post job was lost.
    await _set_updated_at(
        env["maker"],
        p.id,
        datetime.now(UTC) - timedelta(seconds=settings.RECONCILE_STALLED_SECONDS + 100),
    )

    await jobs_mod.reconcile_campaigns(env["ctx"])

    pub = [j for j in env["redis"].jobs if j[0] == "publish_post"]
    assert pub == [("publish_post", (str(p.id),), {"_job_id": f"publish:{p.id}"})]


async def test_reconcile_fresh_approved_left_alone(db, env):
    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        action="like",
        status="approved",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()
    # Recently touched (mid-backoff or just enqueued): not stalled, leave it.
    await _set_updated_at(env["maker"], p.id, datetime.now(UTC) - timedelta(seconds=60))

    await jobs_mod.reconcile_campaigns(env["ctx"])

    assert not [j for j in env["redis"].jobs if j[0] == "publish_post"]


async def test_reconcile_pending_past_stagger_renotifies_once_per_user(db, env):
    user = await _user(db)
    c = Campaign(
        title="C",
        type="amplify",
        status="publishing",
        stagger_min_seconds=5,
        stagger_max_seconds=10,
        launched_at=datetime.now(UTC) - timedelta(seconds=600),
    )
    db.add(c)
    await db.flush()
    # Two pending posts for the same user: the staggered notify was lost.
    for _ in range(2):
        db.add(
            Post(
                campaign_id=c.id,
                user_id=user.id,
                action="like",
                status="pending",
                idempotency_key=uuid.uuid4().hex,
            )
        )
    await db.commit()

    await jobs_mod.reconcile_campaigns(env["ctx"])

    notify = [j for j in env["redis"].jobs if j[0] == "notify_participant"]
    assert notify == [
        (
            "notify_participant",
            (str(c.id), str(user.id)),
            {"_job_id": f"notify:{c.id}:{user.id}"},
        )
    ]


async def test_reconcile_pending_within_stagger_not_notified(db, env):
    user = await _user(db)
    c = Campaign(
        title="C",
        type="amplify",
        status="publishing",
        stagger_min_seconds=60,
        stagger_max_seconds=300,
        launched_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    db.add(c)
    await db.flush()
    db.add(
        Post(
            campaign_id=c.id,
            user_id=user.id,
            action="like",
            status="pending",
            idempotency_key=uuid.uuid4().hex,
        )
    )
    await db.commit()

    await jobs_mod.reconcile_campaigns(env["ctx"])

    # Still inside the stagger window: the legit staggered notify may yet fire.
    assert not [j for j in env["redis"].jobs if j[0] == "notify_participant"]


async def test_reconcile_settles_stuck_completed_campaign(db, env):
    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    # All posts terminal, but a crash left the campaign stuck in publishing.
    db.add(
        Post(
            campaign_id=c.id,
            user_id=user.id,
            action="post",
            status="published",
            external_id="urn:li:share:1",
            idempotency_key="k",
        )
    )
    await db.commit()

    await jobs_mod.reconcile_campaigns(env["ctx"])

    async with env["maker"]() as s:
        rc = await s.get(Campaign, c.id)
        assert rc.status == "completed"


async def test_reconcile_reissues_reminders_past_window(db, env):
    user = await _user(db)
    c = Campaign(
        title="C",
        type="amplify",
        status="publishing",
        launched_at=datetime.now(UTC)
        - timedelta(seconds=settings.REMINDER_DELAY_SECONDS + 60),
    )
    db.add(c)
    await db.flush()
    db.add(
        Post(
            campaign_id=c.id,
            user_id=user.id,
            action="post",
            status="scheduled",
            idempotency_key="k",
        )
    )
    await db.commit()

    await jobs_mod.reconcile_campaigns(env["ctx"])

    remind = [j for j in env["redis"].jobs if j[0] == "send_reminders"]
    assert remind == [("send_reminders", (str(c.id),), {"_job_id": f"remind:{c.id}"})]


async def test_reconcile_no_reminders_within_window(db, env):
    user = await _user(db)
    c = Campaign(
        title="C",
        type="amplify",
        status="publishing",
        launched_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    db.add(c)
    await db.flush()
    db.add(
        Post(
            campaign_id=c.id,
            user_id=user.id,
            action="post",
            status="scheduled",
            idempotency_key="k",
        )
    )
    await db.commit()

    await jobs_mod.reconcile_campaigns(env["ctx"])

    assert not [j for j in env["redis"].jobs if j[0] == "send_reminders"]


async def test_reconcile_one_bad_campaign_does_not_block_others(db, env, monkeypatch):
    user = await _user(db)
    good = Campaign(title="Good", type="amplify", status="publishing")
    bad = Campaign(title="Bad", type="amplify", status="publishing")
    db.add_all([good, bad])
    await db.flush()
    good_post = Post(
        campaign_id=good.id,
        user_id=user.id,
        action="like",
        status="approved",
        idempotency_key="g",
    )
    bad_post = Post(
        campaign_id=bad.id,
        user_id=user.id,
        action="like",
        status="approved",
        idempotency_key="b",
    )
    db.add_all([good_post, bad_post])
    await db.commit()
    stale = datetime.now(UTC) - timedelta(
        seconds=settings.RECONCILE_STALLED_SECONDS + 100
    )
    await _set_updated_at(env["maker"], good_post.id, stale)
    await _set_updated_at(env["maker"], bad_post.id, stale)

    orig = jobs_mod._reconcile_one

    async def flaky(ctx, campaign_id, now, stalled_before):
        if campaign_id == bad.id:
            raise RuntimeError("boom")
        return await orig(ctx, campaign_id, now, stalled_before)

    monkeypatch.setattr(jobs_mod, "_reconcile_one", flaky)

    # Must not raise even though one campaign blows up.
    await jobs_mod.reconcile_campaigns(env["ctx"])

    reenqueued = {
        args[0] for name, args, _ in env["redis"].jobs if name == "publish_post"
    }
    assert str(good_post.id) in reenqueued
