"""Tests for require_onboarded.

A users row exists from the moment Google login succeeds, so a valid token says
nothing about whether the person finished the wizard. These cover the API half
of that gate: the onboarding endpoints stay open, everything else is shut until
the user has both a team and a LinkedIn account.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# Representative gated endpoints across the routers, all read-only so a 200
# proves reachability rather than a side effect.
GATED = [
    "/v1/campaigns",
    "/v1/leaderboard",
    "/v1/users/roster",
    "/v1/teams/all",
]


@pytest.mark.parametrize("path", GATED)
async def test_no_team_is_blocked(client: AsyncClient, as_role, path):
    async with as_role("admin", team=False):
        resp = await client.get(path)
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "onboarding_incomplete"
    assert detail["step"] == 1


@pytest.mark.parametrize("path", GATED)
async def test_no_linkedin_is_blocked(client: AsyncClient, as_role, path):
    async with as_role("admin", linkedin=False):
        resp = await client.get(path)
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "onboarding_incomplete"
    assert detail["step"] == 2


@pytest.mark.parametrize("path", GATED)
async def test_onboarded_user_is_admitted(client: AsyncClient, as_role, path):
    async with as_role("admin"):
        resp = await client.get(path)
    assert resp.status_code == 200


async def test_team_is_checked_before_linkedin(client: AsyncClient, as_role):
    """A user missing both is sent to step 1, not step 2."""
    async with as_role("viewer", team=False, linkedin=False):
        resp = await client.get("/v1/campaigns")
    assert resp.json()["detail"]["step"] == 1


async def test_onboarding_endpoints_stay_open(client: AsyncClient, as_role, engine):
    """The wizard's own calls cannot be gated or the flow deadlocks."""
    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.team import Team

    team = Team(id=uuid.uuid4(), name="Open Teams")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(team)
        await session.commit()

    async with as_role("viewer", team=False, linkedin=False):
        assert (await client.get("/v1/users/me")).status_code == 200
        assert (await client.get("/v1/teams")).status_code == 200
        assert (await client.get("/v1/connections")).status_code == 200
        # Step 1 itself: picking a team must work while still un-onboarded.
        assigned = await client.patch("/v1/users/me", json={"team_id": str(team.id)})
        assert assigned.status_code == 200
        # Still gated, because LinkedIn is the other half.
        assert (await client.get("/v1/campaigns")).status_code == 403


async def test_stale_linkedin_still_counts_as_onboarded(
    client: AsyncClient, as_role, db
):
    """Stale means reconnect, not start over, matching the frontend gate."""
    from sqlalchemy import update

    from app.models.social_account import SocialAccount

    async with as_role("viewer") as user:
        await db.execute(
            update(SocialAccount)
            .where(SocialAccount.user_id == user.id)
            .values(status="stale")
        )
        await db.commit()
        resp = await client.get("/v1/campaigns")
    assert resp.status_code == 200


async def test_role_gate_runs_after_onboarding_gate(client: AsyncClient, as_role):
    """An un-onboarded admin is told to onboard, not that they lack access."""
    async with as_role("admin", linkedin=False):
        resp = await client.get("/v1/users")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "onboarding_incomplete"
