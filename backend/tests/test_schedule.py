"""Scheduled auto-launch: conflict rule, schedule feed, and the cron poll.

The conflict rule and feed are exercised through the API; the poll and its
restart/failure provisions are exercised against the job directly with a fake
Redis, mirroring test_worker_jobs.py.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.workers.jobs as jobs_mod
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign

pytestmark = pytest.mark.asyncio


# --- API: conflict rule, past-date validation, feed --------------------------

_SEED_URL = "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/"


def amplify(
    title: str = "A",
    scheduled_at: str | None = None,
    schedule_timezone: str | None = None,
) -> dict:
    body = {
        "title": title,
        "type": "amplify",
        "seed_url": _SEED_URL,
        "seed_content": "x",
    }
    if scheduled_at is not None:
        body["scheduled_at"] = scheduled_at
    if schedule_timezone is not None:
        body["schedule_timezone"] = schedule_timezone
    return body


async def test_same_day_schedule_rejected_even_in_draft(client, as_role):
    # Two different clock times on the same company-local day collide: a draft
    # still holds the whole day.
    async with as_role("editor"):
        first = await client.post(
            "/v1/campaigns",
            json=amplify("First", "2035-06-15T09:00:00+05:30"),
        )
        assert first.status_code == 201
        second = await client.post(
            "/v1/campaigns",
            json=amplify("Second", "2035-06-15T21:00:00+05:30"),
        )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "schedule_conflict"
    assert detail["campaign_id"] == first.json()["id"]


async def test_different_day_schedule_accepted(client, as_role):
    async with as_role("editor"):
        first = await client.post(
            "/v1/campaigns",
            json=amplify("First", "2035-06-15T09:00:00+05:30"),
        )
        second = await client.post(
            "/v1/campaigns",
            json=amplify("Second", "2035-06-16T09:00:00+05:30"),
        )
    assert first.status_code == 201
    assert second.status_code == 201


async def test_past_schedule_rejected(client, as_role):
    async with as_role("editor"):
        resp = await client.post(
            "/v1/campaigns",
            json=amplify("Past", "2000-01-01T09:00:00+05:30"),
        )
    assert resp.status_code == 422


async def test_clearing_schedule_frees_the_day(client, as_role):
    async with as_role("editor"):
        first = await client.post(
            "/v1/campaigns",
            json=amplify("First", "2035-07-10T09:00:00+05:30"),
        )
        cid = first.json()["id"]
        # Clear the schedule, then a second campaign can take that day.
        cleared = await client.patch(
            f"/v1/campaigns/{cid}", json={"scheduled_at": None}
        )
        assert cleared.status_code == 200
        assert cleared.json()["scheduled_at"] is None
        second = await client.post(
            "/v1/campaigns",
            json=amplify("Second", "2035-07-10T21:00:00+05:30"),
        )
    assert second.status_code == 201


async def test_manual_launch_clears_schedule(client, as_role, db, enqueued):
    async with as_role("editor"):
        created = await client.post(
            "/v1/campaigns",
            json=amplify("Sched", "2035-08-01T09:00:00+05:30"),
        )
        cid = created.json()["id"]
        # Move it to review so launch is allowed, then launch manually.
        campaign = await db.get(Campaign, uuid.UUID(cid))
        campaign.status = "review"
        await db.commit()
        launched = await client.post(f"/v1/campaigns/{cid}/launch")
    assert launched.status_code == 200
    assert launched.json()["scheduled_at"] is None
    # Manual launch uses the same fixed job id as the auto-launch path, so the
    # cron resweep dedupes against it instead of double-fanning-out.
    jobs = [(n, a, k) for n, a, k in enqueued if n == "launch_campaign"]
    assert jobs == [("launch_campaign", (cid,), {"_job_id": f"launch:{cid}"})]


async def test_schedule_feed_returns_range(client, as_role):
    async with as_role("editor"):
        await client.post(
            "/v1/campaigns", json=amplify("June A", "2035-06-05T09:00:00+05:30")
        )
        await client.post(
            "/v1/campaigns", json=amplify("June B", "2035-06-20T09:00:00+05:30")
        )
        # A campaign outside the queried window must not appear.
        await client.post(
            "/v1/campaigns", json=amplify("July", "2035-07-05T09:00:00+05:30")
        )
        resp = await client.get(
            "/v1/campaigns/schedule?start=2035-06-01&end=2035-06-30"
        )
    assert resp.status_code == 200
    entries = resp.json()
    titles = {e["title"] for e in entries}
    assert titles == {"June A", "June B"}
    assert all(e["creator_name"] for e in entries)


async def test_naive_time_read_in_campaign_timezone(client, as_role):
    # A naive datetime-local value is interpreted in the campaign's chosen zone
    # (9am US Pacific in June = PDT, UTC-7) and stored as UTC.
    async with as_role("editor"):
        resp = await client.post(
            "/v1/campaigns",
            json=amplify(
                "PT", "2035-06-15T09:00:00", schedule_timezone="America/Los_Angeles"
            ),
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["schedule_timezone"] == "America/Los_Angeles"
    # 09:00 PDT == 16:00 UTC. SQLite drops the tzinfo in tests, so compare the
    # stored UTC wall-clock (naive) rather than the offset marker.
    stored = datetime.fromisoformat(body["scheduled_at"]).replace(tzinfo=None)
    assert stored == datetime(2035, 6, 15, 16, 0)


async def test_conflict_uses_company_day_across_timezones(client, as_role):
    # Two campaigns entered in different timezones that both land on the same
    # company (IST) calendar day still collide, because the day boundary is the
    # company timezone regardless of each campaign's own zone.
    async with as_role("editor"):
        first = await client.post(
            "/v1/campaigns",
            json=amplify(
                "LA", "2035-11-20T09:00:00", schedule_timezone="America/Los_Angeles"
            ),
        )
        assert first.status_code == 201  # 17:00 UTC -> 22:30 IST, Nov 20 IST
        second = await client.post(
            "/v1/campaigns",
            json=amplify("IN", "2035-11-20T18:00:00", schedule_timezone="Asia/Kolkata"),
        )
    assert second.status_code == 409  # 12:30 UTC -> 18:00 IST, same Nov 20 IST


async def test_unknown_timezone_rejected(client, as_role):
    async with as_role("editor"):
        resp = await client.post(
            "/v1/campaigns",
            json=amplify("Bad", "2035-06-15T09:00:00", schedule_timezone="Mars/Phobos"),
        )
    assert resp.status_code == 422


async def test_update_unknown_timezone_rejected(client, as_role):
    async with as_role("editor"):
        created = await client.post("/v1/campaigns", json=amplify("A"))
        cid = created.json()["id"]
        resp = await client.patch(
            f"/v1/campaigns/{cid}",
            json={
                "scheduled_at": "2035-06-15T09:00:00",
                "schedule_timezone": "Mars/Phobos",
            },
        )
    assert resp.status_code == 422


async def test_update_scheduled_at_uses_stored_timezone(client, as_role):
    # Set a PT timezone first, then PATCH only the time (no tz in the body): the
    # new naive time must be read in the campaign's stored timezone, not the
    # company default.
    async with as_role("editor"):
        created = await client.post(
            "/v1/campaigns",
            json=amplify(
                "PT", "2035-06-15T09:00:00", schedule_timezone="America/Los_Angeles"
            ),
        )
        cid = created.json()["id"]
        updated = await client.patch(
            f"/v1/campaigns/{cid}",
            json={"scheduled_at": "2035-06-16T09:00:00"},
        )
    assert updated.status_code == 200
    body = updated.json()
    assert body["schedule_timezone"] == "America/Los_Angeles"
    # 09:00 PDT == 16:00 UTC (SQLite drops tzinfo in tests).
    stored = datetime.fromisoformat(body["scheduled_at"]).replace(tzinfo=None)
    assert stored == datetime(2035, 6, 16, 16, 0)


async def test_update_changing_timezone_reinterprets_time(client, as_role):
    # Changing the timezone alongside the time reinterprets the wall-clock in the
    # new zone.
    async with as_role("editor"):
        created = await client.post(
            "/v1/campaigns",
            json=amplify("A", "2035-06-15T09:00:00", schedule_timezone="Asia/Kolkata"),
        )
        cid = created.json()["id"]
        updated = await client.patch(
            f"/v1/campaigns/{cid}",
            json={
                "scheduled_at": "2035-06-15T09:00:00",
                "schedule_timezone": "America/Los_Angeles",
            },
        )
    assert updated.status_code == 200
    body = updated.json()
    assert body["schedule_timezone"] == "America/Los_Angeles"
    stored = datetime.fromisoformat(body["scheduled_at"]).replace(tzinfo=None)
    assert stored == datetime(2035, 6, 15, 16, 0)


async def test_schedule_feed_caps_range(client, as_role):
    async with as_role("viewer"):
        resp = await client.get(
            "/v1/campaigns/schedule?start=2035-01-01&end=2035-12-31"
        )
    assert resp.status_code == 422


async def test_schedule_feed_redacts_other_users_campaigns(client, as_role):
    # Campaign visibility in the feed mirrors the rest of the API: a user who is
    # neither the creator, a participant, nor an admin sees the day as taken but
    # not the title or creator name.
    async with as_role("editor", email="owner@corp.com"):
        await client.post(
            "/v1/campaigns", json=amplify("Secret", "2035-09-05T09:00:00+05:30")
        )

    async with as_role("viewer", email="outsider@corp.com"):
        resp = await client.get(
            "/v1/campaigns/schedule?start=2035-09-01&end=2035-09-30"
        )
    assert resp.status_code == 200
    [entry] = resp.json()
    assert entry["title"] == "Reserved"
    assert entry["creator_name"] is None
    assert entry["can_view"] is False

    # An admin sees the real details.
    async with as_role("admin", email="admin@corp.com"):
        resp = await client.get(
            "/v1/campaigns/schedule?start=2035-09-01&end=2035-09-30"
        )
    [entry] = resp.json()
    assert entry["title"] == "Secret"
    assert entry["can_view"] is True


async def test_schedule_conflict_does_not_name_hidden_campaign(client, as_role):
    # The 409 names the blocking campaign only when the caller could view it;
    # otherwise the conflict check would leak titles the API 403s elsewhere.
    async with as_role("editor", email="owner2@corp.com"):
        first = await client.post(
            "/v1/campaigns", json=amplify("Hidden", "2035-10-10T09:00:00+05:30")
        )
        assert first.status_code == 201

    async with as_role("editor", email="rival@corp.com"):
        second = await client.post(
            "/v1/campaigns", json=amplify("Mine", "2035-10-10T21:00:00+05:30")
        )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "schedule_conflict"
    assert "Hidden" not in detail["message"]
    assert "campaign_id" not in detail


# --- Cron poll: launch, missed paths, restart/failure provisions -------------


class _FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple] = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))


@pytest_asyncio.fixture
async def env(engine, monkeypatch):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_mod, "async_session_factory", maker)
    redis = _FakeRedis()
    return {"maker": maker, "ctx": {"redis": redis}, "redis": redis}


async def _audit_actions(maker, campaign_id) -> list[str]:
    async with maker() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(AuditLog.campaign_id == campaign_id)
                )
            )
            .scalars()
            .all()
        )
    return [r.action for r in rows]


async def test_due_review_campaign_auto_launches(db, env):
    c = Campaign(
        title="Due",
        type="amplify",
        status="review",
        seed_urn="urn:li:activity:1",
        scheduled_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    db.add(c)
    await db.commit()

    await jobs_mod.launch_due_campaigns(env["ctx"])

    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        assert refreshed.launched_at is not None
        assert refreshed.launched_by == c.created_by
    launched = [j for j in env["redis"].jobs if j[0] == "launch_campaign"]
    assert launched == [
        ("launch_campaign", (str(c.id),), {"_job_id": f"launch:{c.id}"})
    ]
    assert "campaign_launched" in await _audit_actions(env["maker"], c.id)


async def test_not_ready_campaign_marked_missed(db, env):
    # Due but still a draft (within the grace window): freed and audited, never
    # launched.
    c = Campaign(
        title="NotReady",
        type="amplify",
        status="draft",
        seed_urn="urn:li:activity:1",
        scheduled_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    db.add(c)
    await db.commit()

    await jobs_mod.launch_due_campaigns(env["ctx"])

    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        assert refreshed.launched_at is None
        assert refreshed.scheduled_at is None
    assert not [j for j in env["redis"].jobs if j[0] == "launch_campaign"]
    assert "campaign_schedule_missed" in await _audit_actions(env["maker"], c.id)


async def test_overdue_beyond_grace_marked_missed(db, env):
    # Ready (review) but overdue past the grace window: not launched at the wrong
    # time; treated as missed with the grace_exceeded reason.
    c = Campaign(
        title="Stale",
        type="amplify",
        status="review",
        seed_urn="urn:li:activity:1",
        scheduled_at=datetime.now(UTC) - timedelta(hours=3),
    )
    db.add(c)
    await db.commit()

    await jobs_mod.launch_due_campaigns(env["ctx"])

    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        assert refreshed.launched_at is None
        assert refreshed.scheduled_at is None
    assert not [j for j in env["redis"].jobs if j[0] == "launch_campaign"]
    missed = [
        r
        for r in await _audit_actions(env["maker"], c.id)
        if r == "campaign_schedule_missed"
    ]
    assert missed


async def test_second_tick_does_not_double_launch(db, env):
    c = Campaign(
        title="Once",
        type="amplify",
        status="review",
        seed_urn="urn:li:activity:1",
        scheduled_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    db.add(c)
    await db.commit()

    await jobs_mod.launch_due_campaigns(env["ctx"])
    first = [j for j in env["redis"].jobs if j[0] == "launch_campaign"]
    # A second tick sees launched_at already stamped and skips it entirely (the
    # resweep also skips because the campaign is no longer in review here).
    async with env["maker"]() as s:
        refreshed = await s.get(Campaign, c.id)
        refreshed.status = "publishing"
        await s.commit()
    await jobs_mod.launch_due_campaigns(env["ctx"])
    second = [j for j in env["redis"].jobs if j[0] == "launch_campaign"]
    assert len(first) == 1
    assert len(second) == 1  # no additional launch enqueued


async def test_conditional_stamp_only_wins_once(db, env):
    c = Campaign(
        title="Race",
        type="amplify",
        status="review",
        scheduled_at=datetime.now(UTC),
    )
    db.add(c)
    await db.commit()

    now = datetime.now(UTC)
    async with env["maker"]() as s:
        from app.repositories.campaign_repo import campaign_repo

        won_a = await campaign_repo.stamp_launched_if_unlaunched(
            s, c.id, launched_by=None, now=now
        )
        await s.commit()
    async with env["maker"]() as s:
        from app.repositories.campaign_repo import campaign_repo

        won_b = await campaign_repo.stamp_launched_if_unlaunched(
            s, c.id, launched_by=None, now=now
        )
        await s.commit()
    assert won_a is True
    assert won_b is False


async def test_stamped_but_unlaunched_gets_reenqueued(db, env):
    # A crash between the launch stamp and the enqueue leaves a review campaign
    # with launched_at set. The resweep re-enqueues with the same job id.
    c = Campaign(
        title="Orphan",
        type="amplify",
        status="review",
        seed_urn="urn:li:activity:1",
        launched_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.add(c)
    await db.commit()

    await jobs_mod.launch_due_campaigns(env["ctx"])

    launched = [j for j in env["redis"].jobs if j[0] == "launch_campaign"]
    assert launched == [
        ("launch_campaign", (str(c.id),), {"_job_id": f"launch:{c.id}"})
    ]


async def test_one_bad_campaign_does_not_block_others(db, env, monkeypatch):
    good = Campaign(
        title="Good",
        type="amplify",
        status="review",
        seed_urn="urn:li:activity:1",
        scheduled_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    bad = Campaign(
        title="Bad",
        type="amplify",
        status="review",
        seed_urn="urn:li:activity:2",
        scheduled_at=datetime.now(UTC) - timedelta(seconds=40),
    )
    db.add_all([good, bad])
    await db.commit()

    orig = jobs_mod._process_due_campaign

    async def flaky(ctx, campaign_id, now, grace):
        if campaign_id == bad.id:
            raise RuntimeError("boom")
        return await orig(ctx, campaign_id, now, grace)

    monkeypatch.setattr(jobs_mod, "_process_due_campaign", flaky)

    # Must not raise even though one campaign blows up.
    await jobs_mod.launch_due_campaigns(env["ctx"])

    launched_ids = {
        args[0] for name, args, _ in env["redis"].jobs if name == "launch_campaign"
    }
    assert str(good.id) in launched_ids
