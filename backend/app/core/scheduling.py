"""Scheduling helpers shared by the controller, schedule feed, and cron poll.

The one-campaign-per-day rule and the events calendar are defined in the company
timezone (``settings.SCHEDULE_TIMEZONE``), not UTC, so a "day" matches the team's
local calendar. Storage is always tz-aware UTC.
"""

from datetime import UTC, date, datetime, timedelta

from app.config import settings


def ensure_utc(dt: datetime) -> datetime:
    """Return a tz-aware UTC datetime, reading a naive value as already-UTC.

    Postgres hands back tz-aware datetimes, but SQLite (tests) drops the tzinfo.
    Storage is always UTC, so a naive read is safely interpreted as UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_scheduled_at(dt: datetime) -> datetime:
    """Coerce an incoming schedule time to tz-aware UTC.

    A naive datetime (what a browser ``datetime-local`` field yields) is read as
    company-local time; an aware one is respected. Either way we store UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=settings.schedule_tz)
    return dt.astimezone(UTC)


def local_day_bounds_utc(dt: datetime) -> tuple[datetime, datetime]:
    """UTC [start, end) covering the company-local calendar day of ``dt``."""
    local = dt.astimezone(settings.schedule_tz)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def local_date_range_utc(start: date, end: date) -> tuple[datetime, datetime]:
    """UTC [start, end) spanning company-local days from ``start`` to ``end``.

    ``end`` is inclusive of that whole calendar day, so a from==to request still
    covers a full day.
    """
    tz = settings.schedule_tz
    start_local = datetime(start.year, start.month, start.day, tzinfo=tz)
    end_local = datetime(end.year, end.month, end.day, tzinfo=tz) + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
