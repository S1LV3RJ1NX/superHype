"""Tests for the campaign service: transitions, plan building, completion."""

import uuid

import pytest

from app.config import settings
from app.models.campaign import Campaign
from app.models.post import Post
from app.models.team import Team
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


async def test_expand_amplify_defaults_to_all_three(db):
    u1 = await _user(db)
    u2 = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")

    out = await campaign_service.expand_participants(db, c, [u1.id, u2.id])

    per_user = {u1.id: set(), u2.id: set()}
    for a in out:
        per_user[a.user_id].add(a.action)
    assert per_user[u1.id] == {"like", "comment", "repost_comment"}
    assert per_user[u2.id] == {"like", "comment", "repost_comment"}


async def test_expand_amplify_honors_per_participant_actions(db):
    u1 = await _user(db)
    u2 = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")

    out = await campaign_service.expand_participants(
        db,
        c,
        [u1.id, u2.id],
        actions_by_participant={
            u1.id: ["like", "repost_comment"],  # no comment for u1
            u2.id: ["comment"],
        },
    )

    per_user: dict = {u1.id: [], u2.id: []}
    for a in out:
        per_user[a.user_id].append(a.action)
    # Canonical order preserved, comment dropped for u1.
    assert per_user[u1.id] == ["like", "repost_comment"]
    assert per_user[u2.id] == ["comment"]


async def test_expand_amplify_empty_actions_excludes_participant(db):
    u1 = await _user(db)
    u2 = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")

    out = await campaign_service.expand_participants(
        db,
        c,
        [u1.id, u2.id],
        actions_by_participant={u1.id: [], u2.id: ["like"]},
    )

    users = {a.user_id for a in out}
    assert users == {u2.id}  # u1 contributes nothing
    assert [a.action for a in out] == ["like"]


async def test_expand_distribute_ignores_actions_map(db):
    poster = await _user(db)
    c = await _campaign(db, ctype="distribute", seed_content="seed")

    out = await campaign_service.expand_participants(
        db, c, [poster.id], actions_by_participant={poster.id: ["like"]}
    )

    # Distribute still authors a self post regardless of the amplify actions map.
    assert any(a.action == "post" for a in out)


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
    # The self-comment is a tracked row targeting the author's own post, not a
    # field on the poster row, so it is visible in the plan and can fall back to
    # an assisted-manual step when the socialActions API is unavailable.
    self_comment_row = next(r for r in rows if r.action == "self_comment")
    assert self_comment_row.body == "link in the comments"
    assert self_comment_row.user_id == poster.id
    assert self_comment_row.target_post_id == post_row.id


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


async def test_build_plan_incremental_only_generates_new(db, monkeypatch):
    # Re-planning after adding a participant generates text only for the new
    # person; the existing person's body is preserved (no gateway call, no
    # overwrite of an edit).
    u_a = await _user(db)
    u_b = await _user(db)
    c = await _campaign(
        db, ctype="amplify", seed_urn="urn:li:activity:1", seed_content="seed"
    )

    calls: list[int] = []

    async def fake_interactions(target_text, items, **kw):
        calls.append(len(items))
        return [f"comment-{i}" for i in range(len(items))]

    monkeypatch.setattr(campaign_service, "generate_interactions", fake_interactions)

    await campaign_service.build_plan(
        db, c.id, [Assignment(user_id=u_a.id, action="comment")], generate=True
    )
    assert sum(calls) == 1

    calls.clear()
    await campaign_service.build_plan(
        db,
        c.id,
        [
            Assignment(user_id=u_a.id, action="comment"),
            Assignment(user_id=u_b.id, action="comment"),
        ],
        generate=True,
    )
    # Only the newly added B needs generation.
    assert sum(calls) == 1
    rows = await post_repo.list_for_campaign(db, c.id)
    bodies = {r.user_id: r.body for r in rows if r.action == "comment"}
    assert bodies[u_a.id] == "comment-0"
    assert bodies[u_b.id]


async def test_build_plan_regenerate_rewrites_everyone(db, monkeypatch):
    u_a = await _user(db)
    u_b = await _user(db)
    c = await _campaign(
        db, ctype="amplify", seed_urn="urn:li:activity:1", seed_content="seed"
    )
    calls: list[int] = []

    async def fake_interactions(target_text, items, **kw):
        calls.append(len(items))
        return [f"c-{i}" for i in range(len(items))]

    monkeypatch.setattr(campaign_service, "generate_interactions", fake_interactions)

    await campaign_service.build_plan(
        db, c.id, [Assignment(user_id=u_a.id, action="comment")], generate=True
    )
    calls.clear()
    await campaign_service.build_plan(
        db,
        c.id,
        [
            Assignment(user_id=u_a.id, action="comment"),
            Assignment(user_id=u_b.id, action="comment"),
        ],
        generate=True,
        regenerate=True,
    )
    # regenerate=True discards preserved text, so both are rewritten.
    assert sum(calls) == 2


async def test_build_plan_incremental_drops_removed_participant(db):
    u_a = await _user(db)
    u_b = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")
    await campaign_service.build_plan(
        db,
        c.id,
        [
            Assignment(user_id=u_a.id, action="comment", body="a"),
            Assignment(user_id=u_b.id, action="comment", body="b"),
        ],
        generate=False,
    )
    # De-select B: their pending post is dropped.
    await campaign_service.build_plan(
        db,
        c.id,
        [Assignment(user_id=u_a.id, action="comment", body="a")],
        generate=False,
    )
    rows = await post_repo.list_for_campaign(db, c.id)
    assert {r.user_id for r in rows} == {u_a.id}


async def test_build_plan_manual_replan_keeps_edited_body(db):
    # A manual re-plan (no participant change, no generation) preserves an edit
    # made to a pending post rather than resetting it to an empty assignment body.
    u = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")
    rows = await campaign_service.build_plan(
        db, c.id, [Assignment(user_id=u.id, action="comment")], generate=False
    )
    comment = next(r for r in rows if r.action == "comment")
    comment.body = "hand edited"
    await db.flush()

    # expand_participants sends no body, so without preservation this would blank
    # the comment.
    await campaign_service.build_plan(
        db, c.id, [Assignment(user_id=u.id, action="comment")], generate=False
    )
    refreshed = await post_repo.list_for_campaign(db, c.id)
    assert next(r for r in refreshed if r.action == "comment").body == "hand edited"


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


async def test_expand_amplify_gives_each_member_all_three(db):
    u1 = await _user(db)
    u2 = await _user(db)
    c = await _campaign(db, ctype="amplify", seed_urn="urn:li:activity:1")

    out = await campaign_service.expand_participants(db, c, [u1.id, u2.id])

    assert len(out) == 6
    assert all(a.target_post_index is None for a in out)
    for uid in (u1.id, u2.id):
        assert {a.action for a in out if a.user_id == uid} == {
            "like",
            "comment",
            "repost_comment",
        }


async def test_expand_distribute_posts_and_mesh_no_reposts(db):
    users = [await _user(db) for _ in range(3)]
    ids = [u.id for u in users]
    c = await _campaign(db, ctype="distribute", seed_content="s")

    out = await campaign_service.expand_participants(db, c, ids)

    # One post per member, in list order; no reposts in distribute.
    assert [a.user_id for a in out if a.action == "post"] == ids
    assert not any(a.action == "repost_comment" for a in out)
    # Each member likes and comments on every other member's post, never their own.
    for i, u in enumerate(users):
        expected = [j for j in range(3) if j != i]
        for action in ("like", "comment"):
            targets = sorted(
                a.target_post_index
                for a in out
                if a.user_id == u.id and a.action == action
            )
            assert targets == expected


async def test_expand_distribute_caps_engagement_targets(db, monkeypatch):
    monkeypatch.setattr(settings, "DISTRIBUTE_MAX_ENGAGEMENT_TARGETS", 2)
    users = [await _user(db) for _ in range(5)]
    c = await _campaign(db, ctype="distribute", seed_content="s")

    out = await campaign_service.expand_participants(db, c, [u.id for u in users])

    for u in users:
        likes = [a for a in out if a.user_id == u.id and a.action == "like"]
        assert len(likes) == 2


async def test_expand_distribute_prefers_founder_posts(db, monkeypatch):
    monkeypatch.setattr(settings, "DISTRIBUTE_MAX_ENGAGEMENT_TARGETS", 1)
    founders = Team(name="Founders", is_active=True)
    db.add(founders)
    await db.flush()
    founder = await _user(db)
    founder.team_id = founders.id
    a = await _user(db)
    b = await _user(db)
    await db.flush()
    c = await _campaign(db, ctype="distribute", seed_content="s")

    # Founder is slot 0; with a cap of 1 the others must pick the founder's post.
    out = await campaign_service.expand_participants(db, c, [founder.id, a.id, b.id])
    for uid in (a.id, b.id):
        comments = [x for x in out if x.user_id == uid and x.action == "comment"]
        assert [x.target_post_index for x in comments] == [0]
