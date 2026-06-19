from datetime import UTC, datetime, timedelta

from app.models.campaign import Campaign
from app.repositories.campaign_repo import campaign_repo
from app.schemas.common import PageParams


async def _seed_campaigns(db, n: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n):
        ts = base + timedelta(seconds=i)
        db.add(Campaign(title=f"c{i}", raw_brief="brief", created_at=ts, updated_at=ts))
    await db.flush()


async def test_keyset_pagination_no_overlap_or_gap(db):
    await _seed_campaigns(db, 25)

    seen: list = []
    cursor: str | None = None
    pages = 0
    while True:
        page = await campaign_repo.paginate(
            db, params=PageParams(limit=10, cursor=cursor)
        )
        assert len(page.items) <= 10
        seen.extend(c.id for c in page.items)
        pages += 1
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
        assert pages < 10, "pagination did not terminate"

    # Every row seen exactly once: no gap, no overlap.
    assert len(seen) == 25
    assert len(set(seen)) == 25
    assert pages == 3  # 10 + 10 + 5


async def test_pagination_orders_newest_first(db):
    await _seed_campaigns(db, 5)
    page = await campaign_repo.paginate(db, params=PageParams(limit=5))
    titles = [c.title for c in page.items]
    assert titles == ["c4", "c3", "c2", "c1", "c0"]
    assert page.next_cursor is None


async def test_endpoint_envelope_and_limit_cap(client):
    # limit above the cap (100) is rejected by query validation.
    over = await client.get("/v1/campaigns", params={"limit": 200})
    assert over.status_code == 422

    ok = await client.get("/v1/campaigns", params={"limit": 10})
    assert ok.status_code == 200
    body = ok.json()
    assert body == {"items": [], "next_cursor": None}
