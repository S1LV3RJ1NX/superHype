"""Tests for the campaign service: transitions, plan building, completion."""

import uuid

import pytest

from app.models.campaign import Campaign
from app.models.post import Post
from app.models.user import User
from app.repositories.post_repo import post_repo
from app.schemas.post import Assignment
from app.services import campaign_service
from app.services.campaign_service import TransitionError

pytestmark = pytest.mark.asyncio


async def _user(db, role="viewer") -> User:
    u = User(email=f"{uuid.uuid4().hex}@corp.com", role=role, is_active=True)
    db.add(u)
    await db.flush()
    return u


async def _campaign(db, *, ctype="amplify", **kw) -> Campaign:
    c = Campaign(title="C", type=ctype, status="draft", **kw)
    db.add(c)
    await db.flush()
    return c


async def test_legal_and_illegal_transitions(db):
    c = await _campaign(db)
    await campaign_service.transition(db, c, "review")
    assert c.status == "review"
    await campaign_service.transition(db, c, "publishing")
    assert c.status == "publishing"

    with pytest.raises(TransitionError):
        await campaign_service.transition(db, c, "draft")


async def test_build_plan_amplify_targets_seed_urn(db):
    u1 = await _user(db)
    u2 = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:123")

    rows = await campaign_service.build_plan(
        db,
        c.id,
        [
            Assignment(user_id=u1.id, action="comment", body="great"),
            Assignment(user_id=u2.id, action="like"),
        ],
        generate=False,
    )
    assert len(rows) == 2
    assert all(r.target_external_id == "urn:li:activity:123" for r in rows)
    assert all(r.target_post_id is None for r in rows)
    assert c.status == "review"


async def test_build_plan_distribute_links_target_post(db):
    poster = await _user(db)
    fan = await _user(db)
    c = await _campaign(db, ctype="distribute", seed_content="seed")

    rows = await campaign_service.build_plan(
        db,
        c.id,
        [
            Assignment(user_id=poster.id, action="post", body="variation A"),
            Assignment(
                user_id=fan.id, action="comment", body="nice", target_post_index=0
            ),
        ],
        generate=False,
    )
    post_row = next(r for r in rows if r.action == "post")
    comment_row = next(r for r in rows if r.action == "comment")
    assert post_row.body == "variation A"
    assert comment_row.target_post_id == post_row.id
    assert comment_row.target_external_id is None


async def test_build_plan_copies_media_and_self_comment(db):
    from app.models.asset import Asset

    poster = await _user(db)
    asset = Asset(content_type="image/png", size_bytes=3, data=b"abc")
    db.add(asset)
    await db.flush()
    c = await _campaign(
        db,
        ctype="distribute",
        seed_content="seed",
        image_asset_id=asset.id,
        self_comment="link in the comments",
    )

    rows = await campaign_service.build_plan(
        db,
        c.id,
        [Assignment(user_id=poster.id, action="post", body="A")],
        generate=False,
    )
    post_row = next(r for r in rows if r.action == "post")
    assert post_row.image_asset_id == asset.id
    assert post_row.first_comment == "link in the comments"


async def test_build_plan_distribute_comment_uses_target_body_and_persona(
    db, monkeypatch
):
    from app.models.team import Team

    team = Team(name="Eng", is_active=True, persona="an engineer's voice")
    db.add(team)
    await db.flush()
    poster = await _user(db)
    fan = await _user(db)
    fan.team_id = team.id
    await db.flush()
    c = await _campaign(db, ctype="distribute", seed_content="seed text")

    captured: dict = {}

    async def fake_variations(seed, n, **kw):
        return ["HERO POST BODY"]

    async def fake_interactions(target_text, items, **kw):
        captured["target_text"] = target_text
        captured["items"] = items
        return ["a thoughtful comment"]

    monkeypatch.setattr(campaign_service, "generate_variations", fake_variations)
    monkeypatch.setattr(campaign_service, "generate_interactions", fake_interactions)

    rows = await campaign_service.build_plan(
        db,
        c.id,
        [
            Assignment(user_id=poster.id, action="post"),
            Assignment(user_id=fan.id, action="comment", target_post_index=0),
        ],
        generate=True,
    )

    # The comment is generated from the hero post's body, not the seed text,
    # and carries the commenter's team persona.
    assert captured["target_text"] == "HERO POST BODY"
    assert captured["items"][0]["persona"] == "an engineer's voice"
    comment_row = next(r for r in rows if r.action == "comment")
    assert comment_row.body == "a thoughtful comment"


async def test_build_plan_sets_unique_idempotency_keys(db):
    u = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:9")
    rows = await campaign_service.build_plan(
        db,
        c.id,
        [
            Assignment(user_id=u.id, action="comment", body="a"),
            Assignment(user_id=u.id, action="repost_comment", body="b"),
        ],
        generate=False,
    )
    keys = [r.idempotency_key for r in rows]
    assert len(keys) == len(set(keys))


async def test_build_plan_replaces_pending_but_keeps_published(db):
    u = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")
    # A previously published post must survive a rebuild.
    published = Post(
        campaign_id=c.id,
        user_id=u.id,
        action="comment",
        status="published",
        external_id="urn:li:comment:1",
        idempotency_key="old:published",
    )
    db.add(published)
    await db.flush()

    await campaign_service.build_plan(
        db,
        c.id,
        [Assignment(user_id=u.id, action="comment", body="fresh")],
        generate=False,
    )
    all_posts = await post_repo.list_for_campaign(db, c.id)
    statuses = sorted(p.status for p in all_posts)
    assert statuses == ["pending", "published"]


async def test_build_plan_keeps_scheduled_posts(db):
    u = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:2")
    # An approved post awaiting publish must survive a re-plan.
    scheduled = Post(
        campaign_id=c.id,
        user_id=u.id,
        action="like",
        status="scheduled",
        idempotency_key="old:scheduled",
    )
    db.add(scheduled)
    await db.flush()

    await campaign_service.build_plan(
        db,
        c.id,
        [Assignment(user_id=u.id, action="comment", body="fresh")],
        generate=False,
    )
    all_posts = await post_repo.list_for_campaign(db, c.id)
    statuses = sorted(p.status for p in all_posts)
    assert statuses == ["pending", "scheduled"]


async def test_check_completion_moves_to_completed(db):
    u = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")
    c.status = "publishing"
    await db.flush()
    db.add(
        Post(
            campaign_id=c.id,
            user_id=u.id,
            action="like",
            status="published",
            idempotency_key="k1",
        )
    )
    await db.flush()

    await campaign_service.check_completion(db, c.id)
    assert c.status == "completed"


async def test_check_completion_noop_when_pending(db):
    u = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")
    c.status = "publishing"
    await db.flush()
    db.add(
        Post(
            campaign_id=c.id,
            user_id=u.id,
            action="like",
            status="pending",
            idempotency_key="k2",
        )
    )
    await db.flush()

    await campaign_service.check_completion(db, c.id)
    assert c.status == "publishing"
