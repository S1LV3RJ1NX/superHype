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
    monkeypatch.setattr(jobs_mod, "_provider", lambda: provider)
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


async def test_self_comment_scheduled_then_placed(db, env):
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="distribute", status="publishing")
    db.add(c)
    await db.flush()
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="hello",
        first_comment="Link in comments: https://ex.com",
        status="approved",
        idempotency_key="kself",
    )
    db.add(p)
    await db.commit()

    await jobs_mod.publish_post(env["ctx"], str(p.id))

    # Body published; a deferred self-comment job was scheduled (not placed yet).
    scheduled = [j for j in env["redis"].jobs if j[0] == "place_self_comment"]
    assert len(scheduled) == 1
    assert scheduled[0][1][0] == str(p.id)
    assert not any(ci[0] == "comment" for ci in env["provider"].calls)
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.status == "published"
        assert rp.first_comment_external_id is None

    # Run the deferred job: the author's own comment lands, idempotency marker set.
    await jobs_mod.place_self_comment(env["ctx"], str(p.id))
    com = next(ci for ci in env["provider"].calls if ci[0] == "comment")
    assert com[1] == "urn:li:share:new"
    assert com[2] == "Link in comments: https://ex.com"
    async with env["maker"]() as s:
        rp = await s.get(Post, p.id)
        assert rp.first_comment_external_id == "urn:li:comment:new"

    # Re-running is a no-op once the marker is set.
    before = len([ci for ci in env["provider"].calls if ci[0] == "comment"])
    await jobs_mod.place_self_comment(env["ctx"], str(p.id))
    after = len([ci for ci in env["provider"].calls if ci[0] == "comment"])
    assert before == after


async def test_self_comment_reschedules_after_lost_enqueue(db, env):
    """A crash between the body commit and the schedule enqueue must not lose the
    self-comment: a later publish_post run re-schedules it."""
    user = await _user(db)
    acct = await _account(db, user)
    c = Campaign(title="C", type="distribute", status="publishing")
    db.add(c)
    await db.flush()
    # Body already live (external_id committed) but the deferred job was never
    # enqueued, mirroring a worker crash right after the body commit.
    p = Post(
        campaign_id=c.id,
        user_id=user.id,
        social_account_id=acct.id,
        action="post",
        body="hello",
        first_comment="Link in comments: https://ex.com",
        status="published",
        external_id="urn:li:share:live",
        first_comment_external_id=None,
        idempotency_key="kresume",
    )
    p.published_at = datetime.now(UTC)
    db.add(p)
    await db.commit()

    # Re-invoking publish_post hits the idempotent early-return and re-schedules.
    await jobs_mod.publish_post(env["ctx"], str(p.id))

    scheduled = [j for j in env["redis"].jobs if j[0] == "place_self_comment"]
    assert len(scheduled) == 1
    assert scheduled[0][1][0] == str(p.id)
    # The body was not re-published.
    assert not any(ci[0] == "publish" for ci in env["provider"].calls)


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
