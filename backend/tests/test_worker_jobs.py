"""Tests for ARQ jobs: generation, launch stagger, dependency-aware publish."""

import uuid
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
from app.providers.linkedin import LinkedInAuthError, LinkedInRateLimitError

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


@pytest_asyncio.fixture
async def env(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_mod, "async_session_factory", maker)
    redis = _FakeRedis()
    provider = _StubProvider()
    monkeypatch.setattr(jobs_mod, "_provider", lambda: provider)
    return {
        "maker": maker,
        "ctx": {"redis": redis},
        "redis": redis,
        "provider": provider,
    }


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


async def test_launch_campaign_stagger_and_enqueue(db, env):
    user = await _user(db)
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
    for _ in range(3):
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

    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        assert refreshed.status == "publishing"
    notify = [j for j in env["redis"].jobs if j[0] == "notify_person"]
    assert len(notify) == 3
    for _, _, kwargs in notify:
        assert 10 <= kwargs["_defer_by"] <= 20
    assert any(j[0] == "send_reminders" for j in env["redis"].jobs)


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


async def test_publish_like_completes_campaign(db, env):
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


async def test_distribute_interaction_defers_until_target_live(db, env):
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


async def test_publish_rate_limit_reenqueues_with_retry_after(db, env):
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


async def test_publish_generic_error_backoff_then_fail(db, env):
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


async def test_publish_auth_error_marks_stale_and_reconnect(db, env, monkeypatch):
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
