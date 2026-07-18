"""Tests for the super hyper leaderboard: scoring, brand bonus, window, ranking."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models.post import Post
from app.models.team import Team
from app.models.user import User

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


async def _seed(engine, users=(), posts=(), teams=()):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        for t in teams:
            session.add(t)
        for u in users:
            session.add(u)
        for p in posts:
            session.add(p)
        await session.commit()


def _user(name, *, team_id=None, role="viewer") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{name}@test.local",
        name=name,
        role=role,
        is_active=True,
        team_id=team_id,
    )


def _post(
    user_id,
    action,
    *,
    status="published",
    published_at=NOW,
    acknowledged_at=None,
    body=None,
    image_url=None,
) -> Post:
    return Post(
        id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        user_id=user_id,
        action=action,
        status=status,
        published_at=published_at,
        acknowledged_at=acknowledged_at,
        body=body,
        image_url=image_url,
    )


async def test_scoring_weights(client: AsyncClient, as_role, engine):
    alice = _user("Alice")
    await _seed(
        engine,
        users=[alice],
        posts=[
            _post(alice.id, "like"),
            _post(alice.id, "like"),
            _post(alice.id, "comment"),
            _post(alice.id, "repost_comment"),
        ],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    assert resp.status_code == 200
    entry = next(e for e in resp.json()["entries"] if e["user_id"] == str(alice.id))
    assert entry["likes"] == 2
    assert entry["comments"] == 1
    assert entry["reposts"] == 1
    # 2*1 + 1*3 + 1*5 = 10
    assert entry["score"] == 10


async def test_bookmarks_score_and_pair_with_likes(
    client: AsyncClient, as_role, engine
):
    # X pairs every like with a bookmark; both land published and both score.
    xena = _user("Xena")
    await _seed(
        engine,
        users=[xena],
        posts=[
            _post(xena.id, "like"),
            _post(xena.id, "bookmark"),
            _post(xena.id, "like"),
            _post(xena.id, "bookmark"),
        ],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    entry = next(e for e in resp.json()["entries"] if e["user_id"] == str(xena.id))
    assert entry["likes"] == 2
    assert entry["bookmarks"] == 2
    # 2*1 (like) + 2*2 (bookmark) = 6
    assert entry["score"] == 6


async def test_acknowledged_likes_and_comments_count(
    client: AsyncClient, as_role, engine
):
    bob = _user("Bob")
    await _seed(
        engine,
        users=[bob],
        posts=[
            _post(
                bob.id,
                "like",
                status="acknowledged",
                published_at=None,
                acknowledged_at=NOW,
            ),
            _post(
                bob.id,
                "comment",
                status="acknowledged",
                published_at=None,
                acknowledged_at=NOW,
            ),
        ],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    entry = next(e for e in resp.json()["entries"] if e["user_id"] == str(bob.id))
    assert entry["likes"] == 1
    assert entry["comments"] == 1
    assert entry["score"] == 4


async def test_pending_posts_excluded(client: AsyncClient, as_role, engine):
    carol = _user("Carol")
    await _seed(
        engine,
        users=[carol],
        posts=[
            _post(carol.id, "like", status="pending"),
            _post(carol.id, "comment", status="failed"),
        ],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    assert all(e["user_id"] != str(carol.id) for e in resp.json()["entries"])


async def test_brand_text_post_bonus(client: AsyncClient, as_role, engine, monkeypatch):
    # Pin the brand keywords so the bonus does not depend on the ambient env.
    monkeypatch.setattr(settings, "BRAND_KEYWORDS", "Acme,ACME")
    dave = _user("Dave")
    await _seed(
        engine,
        users=[dave],
        posts=[_post(dave.id, "post", body="Loving the Acme launch")],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    entry = next(e for e in resp.json()["entries"] if e["user_id"] == str(dave.id))
    assert entry["brand_posts"] == 1
    assert entry["score"] == 10


async def test_brand_media_post_bonus(
    client: AsyncClient, as_role, engine, monkeypatch
):
    # Pin the brand keywords so the bonus does not depend on the ambient env.
    monkeypatch.setattr(settings, "BRAND_KEYWORDS", "Acme,ACME")
    erin = _user("Erin")
    await _seed(
        engine,
        users=[erin],
        posts=[
            _post(
                erin.id,
                "post",
                body="ACME ships again",
                image_url="https://x/i.png",
            )
        ],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    entry = next(e for e in resp.json()["entries"] if e["user_id"] == str(erin.id))
    assert entry["brand_posts"] == 1
    assert entry["score"] == 30


async def test_non_brand_post_no_bonus(client: AsyncClient, as_role, engine):
    frank = _user("Frank")
    await _seed(
        engine,
        users=[frank],
        posts=[_post(frank.id, "post", body="Just a normal update")],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    # direct post with no brand mention scores 0, so no leaderboard presence.
    assert all(e["user_id"] != str(frank.id) for e in resp.json()["entries"])


async def test_window_filters_out_old_actions(client: AsyncClient, as_role, engine):
    gina = _user("Gina")
    old = NOW - timedelta(days=400)
    await _seed(
        engine,
        users=[gina],
        posts=[
            _post(gina.id, "comment", published_at=old),
            _post(gina.id, "like", published_at=NOW),
        ],
    )
    start = (NOW - timedelta(days=30)).isoformat()
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard", params={"start": start})
    entry = next(e for e in resp.json()["entries"] if e["user_id"] == str(gina.id))
    # Only the recent like is in window.
    assert entry["comments"] == 0
    assert entry["likes"] == 1
    assert entry["score"] == 1


async def test_ranking_order_and_ranks(client: AsyncClient, as_role, engine):
    low = _user("Low")
    high = _user("High")
    await _seed(
        engine,
        users=[low, high],
        posts=[
            _post(low.id, "like"),
            _post(high.id, "repost_comment"),
            _post(high.id, "repost_comment"),
        ],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    entries = resp.json()["entries"]
    ranked = {e["user_id"]: e for e in entries}
    assert ranked[str(high.id)]["rank"] == 1
    assert ranked[str(low.id)]["rank"] == 2
    assert ranked[str(high.id)]["score"] == 10
    assert ranked[str(low.id)]["score"] == 1


async def test_team_name_hydrated(client: AsyncClient, as_role, engine):
    team = Team(id=uuid.uuid4(), name="GTM", is_active=True)
    heidi = _user("Heidi", team_id=team.id)
    await _seed(
        engine,
        teams=[team],
        users=[heidi],
        posts=[_post(heidi.id, "like")],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard")
    entry = next(e for e in resp.json()["entries"] if e["user_id"] == str(heidi.id))
    assert entry["team_name"] == "GTM"


async def test_limit_caps_results(client: AsyncClient, as_role, engine):
    users = [_user(f"Member{i}") for i in range(5)]
    posts = [_post(u.id, "repost_comment") for u in users]
    await _seed(engine, users=users, posts=posts)
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard", params={"limit": 2})
    entries = resp.json()["entries"]
    assert len(entries) == 2
    assert [e["rank"] for e in entries] == [1, 2]


async def test_end_boundary_is_exclusive(client: AsyncClient, as_role, engine):
    ivan = _user("Ivan")
    boundary = NOW
    await _seed(
        engine,
        users=[ivan],
        posts=[
            # Settled exactly at the end bound: must be excluded (completed_at < end).
            _post(ivan.id, "like", published_at=boundary),
            # Settled a day earlier: must be included.
            _post(ivan.id, "comment", published_at=boundary - timedelta(days=1)),
        ],
    )
    async with as_role("viewer"):
        resp = await client.get("/v1/leaderboard", params={"end": boundary.isoformat()})
    entry = next(e for e in resp.json()["entries"] if e["user_id"] == str(ivan.id))
    assert entry["likes"] == 0
    assert entry["comments"] == 1
    assert entry["score"] == 3


async def test_requires_auth(client: AsyncClient):
    resp = await client.get("/v1/leaderboard")
    assert resp.status_code == 401
