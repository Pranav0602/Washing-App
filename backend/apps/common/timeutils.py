"""UTC time helpers.

The PDF requires all timestamps to be stored in UTC and rendered in the
customer's or partner's local zone. Storage is UTC everywhere (Django
``USE_TZ=True``); these helpers centralise the few places where time windows and
"is this stale" decisions are made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

SUPPORTED_ZONES = ("Asia/Kolkata", "UTC")


def utc_now() -> datetime:
    """Timezone-aware current time in UTC."""
    return timezone.now()


def is_utc(value: datetime) -> bool:
    return timezone.is_aware(value)


def as_utc(value: datetime) -> datetime:
    """Coerce a datetime to UTC, assuming naive values are already UTC."""
    if timezone.is_naive(value):
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def in_timezone(value: datetime, tz_name: str) -> datetime:
    """Render a stored UTC timestamp in the given IANA zone."""
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        zone = UTC
    return as_utc(value).astimezone(zone)


def local_hour(value: datetime, tz_name: str) -> int:
    return in_timezone(value, tz_name).hour


def local_weekday(value: datetime, tz_name: str) -> int:
    """Monday is 0, matching Python's ``date.weekday()``."""
    return in_timezone(value, tz_name).weekday()


def minutes_into_day(value: datetime, tz_name: str) -> int:
    local = in_timezone(value, tz_name)
    return local.hour * 60 + local.minute


def is_within_window(
    value: datetime, tz_name: str, opens_at_minutes: int, closes_at_minutes: int
) -> bool:
    """Whether ``value`` falls inside a daily window given in local minutes.

    Handles windows that wrap past midnight (e.g. 22:00-02:00 for a night-shift
    partner or a late-night service window).
    """
    current = minutes_into_day(value, tz_name)
    if opens_at_minutes <= closes_at_minutes:
        return opens_at_minutes <= current < closes_at_minutes
    return current >= opens_at_minutes or current < closes_at_minutes


def seconds_since(value: datetime) -> float:
    return (utc_now() - as_utc(value)).total_seconds()


def is_stale(value: datetime | None, max_age_seconds: int) -> bool:
    """True when ``value`` is missing or older than the allowed age."""
    if value is None:
        return True
    return seconds_since(value) > max_age_seconds


def add_minutes(value: datetime, minutes: int) -> datetime:
    return as_utc(value) + timedelta(minutes=minutes)


def add_seconds(value: datetime, seconds: int) -> datetime:
    return as_utc(value) + timedelta(seconds=seconds)


def overlaps(
    start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime
) -> bool:
    """Half-open interval overlap: ``[start, end)``."""
    return as_utc(start_a) < as_utc(end_b) and as_utc(start_b) < as_utc(end_a)