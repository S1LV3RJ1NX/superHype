"""Tests for ARQ jobs: generation, launch stagger, dependency-aware publish."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.services.campaign_service as cs_mod
import app.workers.jobs as jobs_mod
from app.core.crypto import encrypt
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.models.user import User
from app.providers.linkedin import (
    LinkedInAPIError,
    LinkedInAuthError,
    LinkedInRateLimitError,
)
from app.workers.queue import flush_campaign_jobs as _real_flush_campaign_jobs

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple] = []
        self.kv: dict = {}

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def delete(self, key):
        self.kv.pop(key, None)


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

    async def bookmark(self, acct, target_urn):
        self.calls.append(("bookmark", target_urn))

    async def refresh(self, acct):
        self.calls.append(("refresh",))
        return {"access_token": "new", "refresh_token": "newr", "expires_in": 7200}


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
    """Turn the automated comment/like path on (Community Management API granted).

    With the flag off (the default), comments and likes are assisted-manual and
    never call the provider; tests of the automated dispatch opt in here.
    """
    from app.config import settings

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


async def test_generate_drafts_happy(db, env, monkeypatch):
    monkeypatch.setattr(
        cs_mod, "generate_variations", AsyncMock(return_value=["body A"])
    )
    monkeypatch.setattr(
        cs_mod, "generate_interactions", AsyncMock(return_value=["great"])
    )
    poster = await _user(db)
    fan = await _user(db)
    c = Campaign(title="C", type="distribute", status="generating", seed_content="s")
    db.add(c)
    await db.commit()

    await jobs_mod.generate_drafts(
        env["ctx"],
        str(c.id),
        [
            {"user_id": str(poster.id), "action": "post"},
            {
                "user_id": str(fan.id),
                "action": "comment",
                "target_post_index": 0,
            },
        ],
    )

    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        assert refreshed.status == "review"
        posts = (await s.execute(select(Post))).scalars().all()
    assert {p.action for p in posts} == {"post", "comment"}
    post_row = next(p for p in posts if p.action == "post")
    assert post_row.body == "body A"


async def test_generate_drafts_failure_marks_failed(db, env, monkeypatch):
    from app.services.generation_service import GenerationError

    monkeypatch.setattr(
        cs_mod,
        "generate_interactions",
        AsyncMock(side_effect=GenerationError("bad json")),
    )
    user = await _user(db)
    c = Campaign(
        title="C", type="amplify", status="generating", seed_urn="urn:li:activity:1"
    )
    db.add(c)
    await db.commit()

    await jobs_mod.generate_drafts(
        env["ctx"],
        str(c.id),
        [{"user_id": str(user.id), "action": "comment"}],
    )
    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        assert refreshed.status == "failed"


async def test_generate_drafts_non_generation_error_marks_failed(db, env, monkeypatch):
    # A non-GenerationError failure (e.g. a DB error inside build_plan) must still
    # move the campaign out of "generating" so the UI does not poll forever.
    monkeypatch.setattr(
        cs_mod,
        "build_plan",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    user = await _user(db)
    c = Campaign(
        title="C", type="amplify", status="generating", seed_urn="urn:li:activity:1"
    )
    db.add(c)
    await db.commit()

    await jobs_mod.generate_drafts(
        env["ctx"],
        str(c.id),
        [{"user_id": str(user.id), "action": "comment"}],
    )
    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        assert refreshed.status == "failed"


async def test_launch_campaign_stagger_and_enqueue(db, env):
    user_a = await _user(db)
    user_b = await _user(db)
    c = Campaign(
        title="C",
        type="amplify",
        status="review",
        seed_urn="urn:li:activity:1",
        stagger_min_seconds=10,
        stagger_max_seconds=20,
    )
    db.add(c)
    await db.flush()
    # user_a owns two posts, user_b one: fan-out is per participant, so we expect
    # one notify_participant job each (not one per post).
    for owner, count in ((user_a, 2), (user_b, 1)):
        for _ in range(count):
            db.add(
                Post(
                    campaign_id=c.id,
                    user_id=owner.id,
                    action="like",
                    status="pending",
                    idempotency_key=uuid.uuid4().hex,
                )
            )
    await db.commit()

    await jobs_mod.launch_campaign(env["ctx"], str(c.id))

    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        assert refreshed.status == "publishing"
    notify = [j for j in env["redis"].jobs if j[0] == "notify_participant"]
    assert len(notify) == 2
    notified_users = {args[1] for _, args, _ in notify}
    assert notified_users == {str(user_a.id), str(user_b.id)}
    for _, args, kwargs in notify:
        assert args[0] == str(c.id)
        assert 10 <= kwargs["_defer_by"] <= 20
    assert any(j[0] == "send_reminders" for j in env["redis"].jobs)


async def test_launch_campaign_stagger_env_override(db, env, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "STAGGER_OVERRIDE_MIN_SECONDS", 1)
    monkeypatch.setattr(settings, "STAGGER_OVERRIDE_MAX_SECONDS", 3)

    user = await _user(db)
    c = Campaign(
        title="C",
        type="amplify",
        status="review",
        seed_urn="urn:li:activity:1",
        stagger_min_seconds=600,
        stagger_max_seconds=1800,
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

    await jobs_mod.launch_campaign(env["ctx"], str(c.id))

    notify = [j for j in env["redis"].jobs if j[0] == "notify_participant"]
    assert len(notify) == 1
    # The env override wins over the campaign's 600-1800 window.
    assert 1 <= notify[0][2]["_defer_by"] <= 3


async def test_publish_post_noop_when_paused(db, env, cm_enabled):
    # A publish enqueued before the campaign was paused must abort when it fires,
    # leaving the post untouched (resume re-enqueues it).
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="paused")
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

    assert env["provider"].calls == []
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "approved"


async def test_publish_post_noop_when_reset(db, env, cm_enabled):
    # A reset rewinds the campaign to review and clears launched_at, so a publish
    # deferred from the previous run must abort rather than post again.
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="review", launched_at=None)
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

    assert env["provider"].calls == []
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "approved"


async def test_flush_campaign_jobs_removes_only_matching(monkeypatch):
    # Reset flushes a campaign's queued jobs: campaign-keyed jobs matched by id
    # and publish_post matched by post id. Other campaigns' jobs are untouched.
    import fakeredis.aioredis
    from arq.connections import ArqRedis
    from arq.constants import default_queue_name
    from arq.jobs import Job

    import app.workers.queue as queue_mod

    fake = fakeredis.aioredis.FakeRedis()
    pool = ArqRedis(connection_pool=fake.connection_pool)
    monkeypatch.setattr(queue_mod, "_pool", pool)

    cid, other_cid = "camp-1", "camp-2"
    mine_post, other_post = "post-mine", "post-other"

    await pool.enqueue_job("notify_participant", cid, "u1", _defer_by=999)
    await pool.enqueue_job("send_reminders", cid, _defer_by=999)
    await pool.enqueue_job("notify_engagements", cid, "u1", _defer_by=999)
    await pool.enqueue_job("publish_post", mine_post, _defer_by=999)
    # Kept: a different campaign and an unrelated post.
    await pool.enqueue_job("notify_participant", other_cid, "u9", _defer_by=999)
    await pool.enqueue_job("publish_post", other_post, _defer_by=999)

    removed = await _real_flush_campaign_jobs(cid, {mine_post})
    assert removed == 4

    remaining = set()
    for raw in await pool.zrange(default_queue_name, 0, -1):
        jid = raw.decode() if isinstance(raw, bytes) else raw
        info = await Job(jid, pool).info()
        remaining.add((info.function, info.args))
    assert remaining == {
        ("notify_participant", (other_cid, "u9")),
        ("publish_post", (other_post,)),
    }

    await pool.aclose()


async def test_notify_participant_noop_when_paused(db, env):
    # A staggered notify that fires after a pause must not schedule the person's
    # posts or DM them.
    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="paused")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        action="like",
        status="pending",
        idempotency_key=uuid.uuid4().hex,
    )
    db.add(p)
    await db.commit()

    await jobs_mod.notify_participant(env["ctx"], str(c.id), str(user.id))

    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "pending"


async def test_notify_engagements_noop_when_paused(db, env, monkeypatch):
    # A deferred engagement nudge that fires after a pause must not DM anyone;
    # resume re-drives it via send_reminders.
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    notify_engagements = AsyncMock()
    monkeypatch.setattr(slack_mod, "notify_engagements", notify_engagements)

    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="paused")
    db.add(c)
    await db.flush()
    db.add(
        Post(
            campaign_id=c.id,
            user_id=user.id,
            action="comment",
            status="action_required",
            idempotency_key=uuid.uuid4().hex,
        )
    )
    await db.commit()

    await jobs_mod.notify_engagements(env["ctx"], str(c.id), str(user.id))

    assert notify_engagements.await_count == 0
    assert fake.closed


async def test_send_reminders_noop_when_paused(db, env, monkeypatch):
    # Reminders must skip a paused campaign entirely; resume re-drives the DMs.
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    notify_participant = AsyncMock()
    notify_engagements = AsyncMock()
    monkeypatch.setattr(slack_mod, "notify_participant", notify_participant)
    monkeypatch.setattr(slack_mod, "notify_engagements", notify_engagements)

    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="paused")
    db.add(c)
    await db.flush()
    db.add(
        Post(
            campaign_id=c.id,
            user_id=user.id,
            action="post",
            status="scheduled",
            idempotency_key=uuid.uuid4().hex,
        )
    )
    await db.commit()

    await jobs_mod.send_reminders(env["ctx"], str(c.id))

    assert notify_participant.await_count == 0
    assert notify_engagements.await_count == 0
    assert fake.closed


async def test_resume_campaign_reenqueues_outstanding(db, env):
    # Resume re-publishes approved posts, re-notifies participants still holding
    # pending posts, and schedules a reminder.
    approver = await _user(db)
    acct = await _account(db, approver)
    pending_user = await _user(db)
    c = Campaign(
        title="C",
        type="amplify",
        status="publishing",
        stagger_min_seconds=1,
        stagger_max_seconds=2,
    )
    db.add(c)
    await db.flush()
    approved = Post(
        campaign_id=c.id,
        user_id=approver.id,
        social_account_id=acct.id,
        action="repost_comment",
        status="approved",
        target_external_id="urn:li:activity:1",
        idempotency_key="a",
    )
    pending = Post(
        campaign_id=c.id,
        user_id=pending_user.id,
        action="like",
        status="pending",
        idempotency_key="b",
    )
    scheduled = Post(
        campaign_id=c.id,
        user_id=approver.id,
        action="comment",
        status="scheduled",
        idempotency_key="c",
    )
    db.add_all([approved, pending, scheduled])
    await db.commit()

    await jobs_mod.resume_campaign(env["ctx"], str(c.id))

    pub = [j for j in env["redis"].jobs if j[0] == "publish_post"]
    assert [a[0] for _, a, _ in pub] == [str(approved.id)]
    notify = [j for j in env["redis"].jobs if j[0] == "notify_participant"]
    assert {a[1] for _, a, _ in notify} == {str(pending_user.id)}
    assert any(j[0] == "send_reminders" for j in env["redis"].jobs)


async def test_resume_campaign_noop_when_not_publishing(db, env):
    # Guard against a stale resume job: if the campaign is not publishing, do
    # nothing.
    c = Campaign(title="C", type="amplify", status="paused")
    db.add(c)
    await db.commit()

    await jobs_mod.resume_campaign(env["ctx"], str(c.id))

    assert env["redis"].jobs == []


async def test_publish_idempotent_noop(db, env):
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
        status="published",
        external_id="urn:li:already",
        idempotency_key="k",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))
    assert env["provider"].calls == []


async def test_publish_like_completes_campaign(db, env, cm_enabled):
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
        rc = await s.get(Campaign, c.id)
        assert rp.status == "published"
        assert rc.status == "completed"
    assert ("like", "urn:li:activity:1") in env["provider"].calls


async def test_publish_comment_assisted_when_cm_disabled(db, env):
    # Flag off (default): a comment is a guided human action, not an API call.
    # The worker resolves the target, sets action_required + engagement_url, and
    # never touches the provider. action_required counts as settled, so a single-
    # post campaign completes.
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="comment",
        body="great work",
        status="approved",
        target_external_id="urn:li:activity:1",
        idempotency_key="kassist",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert env["provider"].calls == []
    assert not [j for j in env["redis"].jobs if j[0] == "publish_post"]
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        rc = await s.get(Campaign, c.id)
        assert rp.status == "action_required"
        assert (
            rp.engagement_url
            == "https://www.linkedin.com/feed/update/urn:li:activity:1/"
        )
        assert rc.status == "completed"

    # Raising the ask enqueues a per-person, deduped engagement nudge for Slack.
    engage = [j for j in env["redis"].jobs if j[0] == "notify_engagements"]
    assert len(engage) == 1
    assert engage[0][1] == (str(c.id), str(user.id))
    assert engage[0][2]["_job_id"] == f"engage:{c.id}:{user.id}"
    assert engage[0][2]["_defer_by"] >= 0

    # Re-running is a no-op: an already-raised ask is not re-raised.
    await jobs_mod.publish_post(env["ctx"], str(p.id))
    assert env["provider"].calls == []


async def test_publish_like_assisted_needs_no_account(db, env):
    # A like has no text and needs no token in assisted mode: even with no
    # connected account the worker raises the human ask.
    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=None,
        action="like",
        status="approved",
        target_external_id="urn:li:activity:9",
        idempotency_key="klike",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert env["provider"].calls == []
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "action_required"
        assert (
            rp.engagement_url
            == "https://www.linkedin.com/feed/update/urn:li:activity:9/"
        )


async def test_distribute_interaction_defers_until_target_live(db, env, cm_enabled):
    poster = await _user(db)
    fan = await _user(db)
    acct = await _account(db, fan)
    c = Campaign(title="C", type="distribute", status="publishing")
    db.add(c)
    await db.flush()
    target = Post(
        campaign_id=c.id,
        user_id=poster.id,
        action="post",
        status="approved",
        idempotency_key="t",
    )
    db.add(target)
    await db.flush()
    interaction = Post(
        campaign_id=c.id,
        user_id=fan.id,
        social_account_id=acct.id,
        action="comment",
        body="nice",
        status="approved",
        target_post_id=target.id,
        idempotency_key="i",
    )
    db.add(interaction)
    await db.commit()

    # Target not yet published -> interaction must defer, not publish.
    await jobs_mod.publish_post(env["ctx"], str(interaction.id))
    assert env["provider"].calls == []
    assert any(
        j[0] == "publish_post" and j[1][0] == str(interaction.id)
        for j in env["redis"].jobs
    )

    # Publish the target, then retry the interaction.
    async with env["maker"]() as s:
        t = await s.get(Post, target.id)
        t.external_id = "urn:li:share:T"
        t.status = "published"
        await s.commit()

    await jobs_mod.publish_post(env["ctx"], str(interaction.id))
    assert ("comment", "urn:li:share:T", "nice") in env["provider"].calls


async def test_distribute_interaction_fails_when_target_skipped(db, env):
    poster = await _user(db)
    fan = await _user(db)
    acct = await _account(db, fan)
    c = Campaign(title="C", type="distribute", status="publishing")
    db.add(c)
    await db.flush()
    target = Post(
        campaign_id=c.id,
        user_id=poster.id,
        action="post",
        status="skipped",
        idempotency_key="t",
    )
    db.add(target)
    await db.flush()
    interaction = Post(
        campaign_id=c.id,
        user_id=fan.id,
        social_account_id=acct.id,
        action="comment",
        body="nice",
        status="approved",
        target_post_id=target.id,
        idempotency_key="i",
    )
    db.add(interaction)
    await db.commit()

    # Target was skipped -> stop deferring; the interaction fails terminally.
    await jobs_mod.publish_post(env["ctx"], str(interaction.id))
    assert env["provider"].calls == []
    assert not any(j[0] == "publish_post" for j in env["redis"].jobs)
    async with env["maker"]() as s:
        ri = await s.get(Post, interaction.id)
        assert ri.status == "failed"


async def test_publish_rate_limit_reenqueues_with_retry_after(db, env, cm_enabled):
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

    deferred = [j for j in env["redis"].jobs if j[0] == "publish_post"]
    assert len(deferred) == 1
    assert deferred[0][2]["_defer_by"] == 42
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "approved"  # not failed; will retry


async def test_publish_generic_error_backoff_then_fail(db, env, cm_enabled):
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

    async def _boom(*a, **k):
        raise RuntimeError("transient")

    env["provider"].like = _boom

    # First failure: increments retries and re-enqueues with backoff.
    await jobs_mod.publish_post(env["ctx"], str(p.id))
    deferred = [j for j in env["redis"].jobs if j[0] == "publish_post"]
    assert len(deferred) == 1
    assert deferred[0][2]["_defer_by"] >= 60
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "approved"
        assert rp.retries == 1

    # Exhaust the remaining retries; the post ends terminally failed.
    for _ in range(jobs_mod.MAX_RETRIES):
        await jobs_mod.publish_post(env["ctx"], str(p.id))
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "failed"


async def test_publish_comment_403_fails_fast_with_scope_message(db, env, cm_enabled):
    # Comments need w_member_social_feed; a 403 must fail immediately (no retry)
    # with an actionable message about the Community Management API.
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="comment",
        body="nice",
        status="approved",
        target_external_id="urn:li:activity:1",
        idempotency_key="k403",
    )
    db.add(p)
    await db.commit()

    async def _forbidden(*a, **k):
        raise LinkedInAPIError(403, "ACCESS_DENIED")

    env["provider"].comment = _forbidden

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    # No retry was scheduled.
    assert not [j for j in env["redis"].jobs if j[0] == "publish_post"]
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "failed"
        assert rp.retries == 0
        assert "w_member_social_feed" in (rp.error or "")
        assert "Community Management" in (rp.error or "")


async def test_publish_reshare_422_activity_parent_fails_fast(db, env):
    # Resharing a feed "activity" URN is rejected by LinkedIn (reshareContext
    # parent must be a share/ugcPost). It never succeeds on retry, so fail fast
    # with an actionable message instead of leaving the card stuck "processing".
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="repost_comment",
        body="my take",
        status="approved",
        target_external_id="urn:li:activity:7477947018389319681",
        idempotency_key="k422",
    )
    db.add(p)
    await db.commit()

    async def _bad_parent(*a, **k):
        raise LinkedInAPIError(
            422,
            '{"message":"ERROR :: /reshareContext/parent :: parent value '
            "urn:li:activity:7477947018389319681 is of type activity. Allowed URN "
            'types are groupPost, share, ugcPost"}',
        )

    env["provider"].reshare = _bad_parent

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    # No retry scheduled; it fails immediately with a reshare-specific message.
    assert not [j for j in env["redis"].jobs if j[0] == "publish_post"]
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "failed"
        assert rp.retries == 0
        assert "reshare" in (rp.error or "").lower()


async def test_publish_reshare_duplicate_adopts_existing_urn(db, env):
    # After a reset and relaunch, resharing identical content is refused by
    # LinkedIn with a 422 duplicate that names the live URN. We adopt it and mark
    # the post published (idempotent recovery), never retry, never fail.
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="repost_comment",
        body="my take",
        status="approved",
        target_external_id="urn:li:share:123",
        idempotency_key="kdup",
    )
    db.add(p)
    await db.commit()

    async def _dupe(*a, **k):
        raise LinkedInAPIError(
            422,
            '{"message":"Content is a duplicate of '
            'urn:li:share:7478151033798680577","errorDetails":{"inputErrors":'
            '[{"code":"DUPLICATE_POST"}]}}',
        )

    env["provider"].reshare = _dupe

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert not [j for j in env["redis"].jobs if j[0] == "publish_post"]
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        rc = await s.get(Campaign, c.id)
        assert rp.status == "published"
        assert rp.external_id == "urn:li:share:7478151033798680577"
        assert rp.error is None
        assert rc.status == "completed"


async def test_publish_auth_error_marks_stale_and_reconnect(
    db, env, monkeypatch, cm_enabled
):
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

    async def _boom(*a, **k):
        raise LinkedInAuthError(401, "bad token")

    env["provider"].like = _boom

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        ra = await s.get(SocialAccount, acct.id)
        assert rp.status == "failed"
        assert ra.status == "stale"
    assert any(j[0] == "request_reconnect" for j in env["redis"].jobs)


async def test_publish_first_comment_places_link(db, env):
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(
        title="C",
        type="distribute",
        status="publishing",
        link="https://ex.com",
        link_placement="first_comment",
    )
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="hello world",
        status="approved",
        idempotency_key="k1",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    calls = env["provider"].calls
    pub = next(ci for ci in calls if ci[0] == "publish")
    assert pub[2].get("link_in_body") is False
    com = next(ci for ci in calls if ci[0] == "comment")
    assert com[1] == "urn:li:share:new"
    assert com[2] == "https://ex.com"
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        rc = await s.get(Campaign, c.id)
        assert rp.status == "published"
        assert rp.external_id == "urn:li:share:new"
        assert rp.first_comment_external_id == "urn:li:comment:new"
        assert rc.status == "completed"


async def test_publish_first_comment_resumes_after_body(db, env):
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(
        title="C",
        type="distribute",
        status="publishing",
        link="https://ex.com",
        link_placement="first_comment",
    )
    db.add(c)
    await db.flush()
    # Body already live from a prior attempt; only the first comment is pending.
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="hello",
        status="approved",
        external_id="urn:li:share:existing",
        idempotency_key="k2",
    )
    p.published_at = datetime.now(UTC)
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    calls = env["provider"].calls
    assert not any(ci[0] == "publish" for ci in calls)
    com = next(ci for ci in calls if ci[0] == "comment")
    assert com[1] == "urn:li:share:existing"
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "published"
        assert rp.first_comment_external_id == "urn:li:comment:new"


async def test_publish_body_placement_no_first_comment(db, env):
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(
        title="C",
        type="distribute",
        status="publishing",
        link="https://ex.com",
        link_placement="body",
    )
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="hello",
        status="approved",
        idempotency_key="k3",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    calls = env["provider"].calls
    pub = next(ci for ci in calls if ci[0] == "publish")
    assert pub[2].get("link_in_body") is True
    assert not any(ci[0] == "comment" for ci in calls)
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "published"
        assert rp.first_comment_external_id is None


async def test_publish_first_comment_403_rolls_back_immediately(db, env):
    # First-comment placement also needs w_member_social_feed. A 403 there must
    # roll back the already-live body (all-or-nothing) and fail fast, not retry.
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(
        title="C",
        type="distribute",
        status="publishing",
        link="https://ex.com",
        link_placement="first_comment",
    )
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="hello",
        status="approved",
        idempotency_key="k403fc",
    )
    db.add(p)
    await db.commit()

    async def _forbidden(*a, **k):
        raise LinkedInAPIError(403, "ACCESS_DENIED")

    env["provider"].comment = _forbidden

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    calls = env["provider"].calls
    # Body published once, then rolled back; no retry was scheduled.
    assert sum(1 for ci in calls if ci[0] == "publish") == 1
    assert ("delete_post", "urn:li:share:new") in calls
    assert not [j for j in env["redis"].jobs if j[0] == "publish_post"]
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "failed"
        assert rp.retries == 0
        assert "first comment" in (rp.error or "")
        assert "w_member_social_feed" in (rp.error or "")


async def test_publish_first_comment_permanent_failure_rolls_back(db, env):
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(
        title="C",
        type="distribute",
        status="publishing",
        link="https://ex.com",
        link_placement="first_comment",
    )
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="hello",
        status="approved",
        idempotency_key="k4",
    )
    db.add(p)
    await db.commit()

    async def _boom(*a, **k):
        raise RuntimeError("comment failed")

    env["provider"].comment = _boom

    # Body publishes on the first pass, then every comment attempt fails until the
    # retry cap, at which point the post is rolled back (deleted) and marked failed.
    for _ in range(jobs_mod.MAX_RETRIES + 1):
        await jobs_mod.publish_post(env["ctx"], str(p.id))

    calls = env["provider"].calls
    assert ("delete_post", "urn:li:share:new") in calls
    # The body is published exactly once despite many attempts (no double post).
    assert sum(1 for ci in calls if ci[0] == "publish") == 1
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "failed"


async def _asset(
    db, *, content_type: str, data: bytes = b"\x00\x00\x00\x18"
) -> uuid.UUID:
    from app.models.asset import Asset

    asset = Asset(content_type=content_type, size_bytes=len(data), data=data)
    db.add(asset)
    await db.flush()
    return asset.id


async def test_publish_post_with_video_asset_uploads_video(db, env):
    user = await _user(db)
    acct = await _account(db, user)
    video_id = await _asset(db, content_type="video/mp4")
    c = Campaign(title="C", type="distribute", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="watch this",
        image_asset_id=video_id,
        status="approved",
        idempotency_key="kvid",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    calls = env["provider"].calls
    assert any(ci[0] == "upload_video" for ci in calls)
    assert not any(ci[0] == "upload_image" for ci in calls)
    pub = next(ci for ci in calls if ci[0] == "publish")
    assert pub[2].get("image_urn") == "urn:li:video:1"
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.image_asset_urn == "urn:li:video:1"
        assert rp.status == "published"


async def test_publish_post_with_image_asset_uploads_image(db, env):
    user = await _user(db)
    acct = await _account(db, user)
    image_id = await _asset(db, content_type="image/png")
    c = Campaign(title="C", type="distribute", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="see this",
        image_asset_id=image_id,
        status="approved",
        idempotency_key="kimg",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    calls = env["provider"].calls
    assert any(ci[0] == "upload_image" for ci in calls)
    assert not any(ci[0] == "upload_video" for ci in calls)
    pub = next(ci for ci in calls if ci[0] == "publish")
    assert pub[2].get("image_urn") == "urn:li:image:1"


async def test_self_comment_assisted_when_cm_disabled(db, env):
    # Flag off (default): the author's self-comment is a guided human action on
    # their own post, not an API call. Once the post is live, the worker resolves
    # the own-post target, sets action_required + engagement_url, and never calls
    # the provider. It is a tracked row, so it settles the campaign.
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="distribute", status="publishing")
    db.add(c)
    await db.flush()
    post = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="hello",
        status="published",
        external_id="urn:li:share:LIVE",
        idempotency_key="kpost",
    )
    post.published_at = datetime.now(UTC)
    db.add(post)
    await db.flush()
    sc = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="self_comment",
        body="For more details: https://ex.com",
        status="approved",
        target_post_id=post.id,
        idempotency_key="kself",
    )
    db.add(sc)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(sc.id))

    assert not any(ci[0] == "comment" for ci in env["provider"].calls)
    assert not [j for j in env["redis"].jobs if j[0] == "publish_post"]
    async with env["maker"]() as s:
        rp = await s.get(Post, sc.id)
        assert rp.status == "action_required"
        assert (
            rp.engagement_url
            == "https://www.linkedin.com/feed/update/urn:li:share:LIVE/"
        )

    # Re-running is a no-op: an already-raised ask is not re-raised.
    await jobs_mod.publish_post(env["ctx"], str(sc.id))
    assert not any(ci[0] == "comment" for ci in env["provider"].calls)


async def test_self_comment_defers_until_own_post_live_then_comments(
    db, env, cm_enabled
):
    # With the socialActions API enabled, the self-comment publishes via the API,
    # but only after the author's own post is live: it defers until then.
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="distribute", status="publishing")
    db.add(c)
    await db.flush()
    post = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        status="approved",
        idempotency_key="kpost",
    )
    db.add(post)
    await db.flush()
    sc = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="self_comment",
        body="For more details: https://ex.com",
        status="approved",
        target_post_id=post.id,
        idempotency_key="kself",
    )
    db.add(sc)
    await db.commit()

    # Own post not yet published -> self-comment defers, does not comment.
    await jobs_mod.publish_post(env["ctx"], str(sc.id))
    assert not any(ci[0] == "comment" for ci in env["provider"].calls)
    assert any(
        j[0] == "publish_post" and j[1][0] == str(sc.id) for j in env["redis"].jobs
    )

    # Publish the own post, then retry: the self-comment lands on it via the API.
    async with env["maker"]() as s:
        t = await s.get(Post, post.id)
        t.external_id = "urn:li:share:MINE"
        t.status = "published"
        await s.commit()

    await jobs_mod.publish_post(env["ctx"], str(sc.id))
    assert (
        "comment",
        "urn:li:share:MINE",
        "For more details: https://ex.com",
    ) in env["provider"].calls


async def test_publish_defers_on_min_gap(db, env, cm_enabled):
    from app.config import settings

    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    recent = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        status="published",
        external_id="urn:li:share:old",
        idempotency_key="recent",
    )
    recent.published_at = datetime.now(UTC)
    db.add(recent)
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="like",
        status="approved",
        target_external_id="urn:li:activity:1",
        idempotency_key="k5",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert not any(ci[0] == "like" for ci in env["provider"].calls)
    deferred = [j for j in env["redis"].jobs if j[0] == "publish_post"]
    assert deferred
    assert (
        0 < deferred[0][2]["_defer_by"] <= settings.MIN_SECONDS_BETWEEN_ACCOUNT_ACTIONS
    )
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "approved"


class _FakeSlackClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def test_send_reminders_re_dms_only_outstanding(db, env, monkeypatch):
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    notify_participant = AsyncMock()
    notify_engagements = AsyncMock()
    # jobs.py calls through the slack_service module, so patching its attrs here
    # is what the job sees (jobs_mod.slack_service is this same module object).
    monkeypatch.setattr(slack_mod, "notify_participant", notify_participant)
    monkeypatch.setattr(slack_mod, "notify_engagements", notify_engagements)

    approver = await _user(db)
    engager = await _user(db)
    settled = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    # approver still owes an approval, engager still owes an engagement, and
    # settled has only terminal posts (nothing to remind).
    db.add_all(
        [
            Post(
                campaign_id=c.id,
                user_id=approver.id,
                action="post",
                status="scheduled",
                idempotency_key=uuid.uuid4().hex,
            ),
            Post(
                campaign_id=c.id,
                user_id=engager.id,
                action="comment",
                status="action_required",
                idempotency_key=uuid.uuid4().hex,
            ),
            Post(
                campaign_id=c.id,
                user_id=settled.id,
                action="like",
                status="acknowledged",
                idempotency_key=uuid.uuid4().hex,
            ),
        ]
    )
    await db.commit()

    await jobs_mod.send_reminders(env["ctx"], str(c.id))

    assert notify_participant.await_count == 1
    assert notify_engagements.await_count == 1
    reminded_approval = {
        str(call.args[3].id) for call in notify_participant.await_args_list
    }
    assert reminded_approval == {str(approver.id)}
    reminded_engage = {
        str(call.args[3].id) for call in notify_engagements.await_args_list
    }
    assert reminded_engage == {str(engager.id)}
    assert fake.closed


async def test_notify_participant_schedules_and_dms(db, env, monkeypatch):
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    notify_participant = AsyncMock()
    monkeypatch.setattr(slack_mod, "notify_participant", notify_participant)

    user = await _user(db)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
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

    await jobs_mod.notify_participant(env["ctx"], str(c.id), str(user.id))

    # The person's pending posts are moved to scheduled with or without Slack.
    async with env["maker"]() as s:
        rows = (await s.execute(select(Post))).scalars().all()
        assert {r.status for r in rows} == {"scheduled"}
    assert notify_participant.await_count == 1
    assert len(notify_participant.await_args.args[4]) == 2  # the two posts


async def _x_acct_status(db, user, *, status="active") -> SocialAccount:
    acct = SocialAccount(
        user_id=user.id,
        platform="x",
        external_urn="123",
        display_name="X",
        access_token_enc=encrypt("tok"),
        refresh_token_enc=encrypt("r"),
        scopes=["tweet.write"],
        status=status,
    )
    db.add(acct)
    await db.flush()
    return acct


async def _x_amplify_like(db, user):
    c = Campaign(title="C", type="amplify", platform="x", status="publishing")
    db.add(c)
    await db.flush()
    db.add(
        Post(
            campaign_id=c.id,
            user_id=user.id,
            platform="x",
            action="like",
            status="pending",
            idempotency_key=uuid.uuid4().hex,
        )
    )
    await db.commit()
    return c


async def test_notify_participant_holds_card_when_x_not_connected(db, env, monkeypatch):
    """An unconnected X participant gets a reconnect DM, not an approve card, and
    their posts stay pending so a later reconnect can re-fire the card."""
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    notify_participant = AsyncMock()
    notify_reconnect = AsyncMock()
    monkeypatch.setattr(slack_mod, "notify_participant", notify_participant)
    monkeypatch.setattr(slack_mod, "notify_reconnect", notify_reconnect)

    user = await _user(db)
    c = await _x_amplify_like(db, user)  # no X account for this user

    await jobs_mod.notify_participant(env["ctx"], str(c.id), str(user.id))

    assert notify_reconnect.await_count == 1
    assert notify_participant.await_count == 0
    async with env["maker"]() as s:
        rows = (await s.execute(select(Post))).scalars().all()
        assert {r.status for r in rows} == {"pending"}


async def test_notify_participant_holds_card_when_x_stale(db, env, monkeypatch):
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    notify_participant = AsyncMock()
    notify_reconnect = AsyncMock()
    monkeypatch.setattr(slack_mod, "notify_participant", notify_participant)
    monkeypatch.setattr(slack_mod, "notify_reconnect", notify_reconnect)

    user = await _user(db)
    await _x_acct_status(db, user, status="stale")
    c = await _x_amplify_like(db, user)

    await jobs_mod.notify_participant(env["ctx"], str(c.id), str(user.id))

    assert notify_reconnect.await_count == 1
    assert notify_participant.await_count == 0


async def test_notify_participant_fires_when_x_connected(db, env, monkeypatch):
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    notify_participant = AsyncMock()
    notify_reconnect = AsyncMock()
    monkeypatch.setattr(slack_mod, "notify_participant", notify_participant)
    monkeypatch.setattr(slack_mod, "notify_reconnect", notify_reconnect)

    user = await _user(db)
    await _x_acct_status(db, user, status="active")
    c = await _x_amplify_like(db, user)

    await jobs_mod.notify_participant(env["ctx"], str(c.id), str(user.id))

    assert notify_reconnect.await_count == 0
    assert notify_participant.await_count == 1
    async with env["maker"]() as s:
        rows = (await s.execute(select(Post))).scalars().all()
        assert {r.status for r in rows} == {"scheduled"}


async def test_handle_slack_interaction_job_delegates(db, env, monkeypatch):
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    handle = AsyncMock()
    monkeypatch.setattr(slack_mod, "handle_interaction", handle)

    payload = {"type": "block_actions", "actions": [{"action_id": "x"}]}
    await jobs_mod.handle_slack_interaction(env["ctx"], payload)

    assert handle.await_count == 1
    assert handle.await_args.args[2] == payload
    assert fake.closed


async def test_request_reconnect_dms_account_owner(db, env, monkeypatch):
    import app.services.slack_service as slack_mod

    fake = _FakeSlackClient()
    monkeypatch.setattr(jobs_mod, "build_slack_client", lambda: fake)
    notify_reconnect = AsyncMock()
    monkeypatch.setattr(slack_mod, "notify_reconnect", notify_reconnect)

    user = await _user(db)
    acct = await _account(db, user)
    await db.commit()

    await jobs_mod.request_reconnect(env["ctx"], str(acct.id))

    assert notify_reconnect.await_count == 1
    assert str(notify_reconnect.await_args.args[2].id) == str(user.id)
    assert fake.closed


async def _x_account(db, user, *, expires_at=None) -> SocialAccount:
    acct = SocialAccount(
        user_id=user.id,
        platform="x",
        external_urn="9000001",
        display_name="T",
        access_token_enc=encrypt("x-tok"),
        refresh_token_enc=encrypt("x-refresh"),
        scopes=["tweet.write"],
        expires_at=expires_at,
        status="active",
    )
    db.add(acct)
    await db.flush()
    return acct


async def test_publish_x_comment_assisted(db, env):
    # X replies to a post the member did not author are blocked by the API, so a
    # comment runs assisted-manual: the worker resolves the target, sets
    # action_required + a tweet deep link, and never calls the provider.
    user = await _user(db)
    acct = await _x_account(db, user)
    c = Campaign(title="C", type="amplify", platform="x", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        platform="x",
        action="comment",
        body="nice one",
        status="approved",
        target_external_id="999",
        idempotency_key="kx1",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert not any(ci[0] == "comment" for ci in env["provider"].calls)
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "action_required"
        assert rp.engagement_url == "https://x.com/i/web/status/999"


async def test_publish_x_quote_assisted(db, env):
    # A quote post (repost_comment) of another member's tweet is likewise blocked
    # by the API, so it runs assisted-manual with the quote commentary handed over
    # to paste and no provider call.
    user = await _user(db)
    acct = await _x_account(db, user)
    c = Campaign(title="C", type="amplify", platform="x", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        platform="x",
        action="repost_comment",
        body="worth a read",
        status="approved",
        target_external_id="999",
        idempotency_key="kx-quote",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert not any(ci[0] in ("reshare", "publish") for ci in env["provider"].calls)
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "action_required"
        assert rp.engagement_url == "https://x.com/i/web/status/999"


async def test_publish_x_bookmark_dispatches(db, env):
    user = await _user(db)
    acct = await _x_account(db, user)
    c = Campaign(title="C", type="amplify", platform="x", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        platform="x",
        action="bookmark",
        status="approved",
        target_external_id="999",
        idempotency_key="kx2",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert ("bookmark", "999") in env["provider"].calls
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "published"


async def test_publish_x_without_account_names_platform(db, env):
    user = await _user(db)
    c = Campaign(title="C", type="amplify", platform="x", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=None,
        platform="x",
        action="like",
        status="approved",
        target_external_id="999",
        idempotency_key="kx3",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "failed"
        assert "No connected X account." in (rp.error or "")


async def test_ensure_fresh_token_refreshes_near_expiry(db, env):
    # An X token expiring inside the refresh buffer is proactively rotated and
    # the new pair persisted (X refresh tokens are single-use).
    from app.core.crypto import decrypt

    user = await _user(db)
    acct = await _x_account(
        db, user, expires_at=datetime.now(UTC) + timedelta(minutes=2)
    )
    await db.commit()

    await jobs_mod._ensure_fresh_token(db, acct, env["redis"])

    assert ("refresh",) in env["provider"].calls
    assert decrypt(acct.access_token_enc) == "new"
    assert decrypt(acct.refresh_token_enc) == "newr"
    assert acct.expires_at > datetime.now(UTC) + timedelta(hours=1)
    # The per-account refresh lock is released afterwards.
    assert f"super-hype:token-refresh:{acct.id}" not in env["redis"].kv


async def test_ensure_fresh_token_skips_when_healthy(db, env):
    user = await _user(db)
    acct = await _x_account(db, user, expires_at=datetime.now(UTC) + timedelta(hours=2))
    await db.commit()

    await jobs_mod._ensure_fresh_token(db, acct, env["redis"])

    assert env["provider"].calls == []


async def test_ensure_fresh_token_skips_without_refresh_token(db, env):
    # LinkedIn accounts usually hold no refresh token: never attempt a refresh.
    user = await _user(db)
    acct = await _account(db, user)
    acct.expires_at = datetime.now(UTC) + timedelta(minutes=2)
    await db.commit()

    await jobs_mod._ensure_fresh_token(db, acct, env["redis"])

    assert env["provider"].calls == []


async def test_ensure_fresh_token_serialized_by_account_lock(db, env, monkeypatch):
    # X refresh tokens are single-use: while another job holds the per-account
    # lock and commits a rotated pair, a waiting job must re-read that pair and
    # skip its own refresh instead of burning the same stored token.
    import asyncio

    from app.core.crypto import decrypt, encrypt

    monkeypatch.setattr(jobs_mod, "_TOKEN_REFRESH_WAIT_SECONDS", 0.01)
    user = await _user(db)
    acct = await _x_account(
        db, user, expires_at=datetime.now(UTC) + timedelta(minutes=2)
    )
    await db.commit()

    lock_key = f"super-hype:token-refresh:{acct.id}"
    await env["redis"].set(lock_key, "1", nx=True)

    async def _winner_commits_and_releases():
        async with env["maker"]() as s:
            other = await s.get(SocialAccount, acct.id)
            other.access_token_enc = encrypt("winner")
            other.expires_at = datetime.now(UTC) + timedelta(hours=2)
            await s.commit()
        await env["redis"].delete(lock_key)

    winner = asyncio.create_task(_winner_commits_and_releases())
    await jobs_mod._ensure_fresh_token(db, acct, env["redis"])
    await winner

    assert env["provider"].calls == []
    assert decrypt(acct.access_token_enc) == "winner"


async def test_provider_registry_routes_by_platform():
    from app.providers.linkedin import linkedin_provider
    from app.providers.x import x_provider

    assert jobs_mod._provider("linkedin") is linkedin_provider
    assert jobs_mod._provider("x") is x_provider
    # Unknown platforms fall back to LinkedIn rather than crashing the worker.
    assert jobs_mod._provider("unknown") is linkedin_provider


async def test_publish_defers_on_daily_cap(db, env, cm_enabled):
    from app.config import settings

    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="amplify", status="publishing")
    db.add(c)
    await db.flush()
    cap = settings.MAX_ACTIONS_PER_ACCOUNT_PER_DAY
    for i in range(cap):
        # Spread across the day so min-gap passes but the daily cap is hit.
        pr = Post(
            campaign_id=c.id,
            user_id=user.id,
            social_account_id=acct.id,
            action="post",
            status="published",
            external_id=f"urn:li:share:{i}",
            idempotency_key=f"old{i}",
        )
        pr.published_at = datetime.now(UTC) - timedelta(hours=i + 1)
        db.add(pr)
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="like",
        status="approved",
        target_external_id="urn:li:activity:1",
        idempotency_key="k6",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    assert not any(ci[0] == "like" for ci in env["provider"].calls)
    deferred = [j for j in env["redis"].jobs if j[0] == "publish_post"]
    assert deferred
    assert deferred[0][2]["_defer_by"] >= 60
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "approved"
