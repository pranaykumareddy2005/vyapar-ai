"""Analytics time-period resolution.

Computes a UTC ``[start, end)`` range for a named period, with day/month boundaries
taken in the configured business timezone (default UTC) and then converted to UTC -
so a UTC ``created_at`` column is never compared against a local date silently.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


class Period(enum.StrEnum):
    TODAY = "today"
    MONTH = "month"
    ALL = "all"


def resolve_period(
    period: Period, tz_name: str, *, now: datetime | None = None
) -> tuple[datetime | None, datetime | None]:
    """Return ``(start_utc, end_utc)`` for the period; ``(None, None)`` for ALL.

    ``end`` is exclusive. ``now`` may be supplied for deterministic testing.
    """
    if period is Period.ALL:
        return None, None

    tz = ZoneInfo(tz_name)
    current = (now or datetime.now(UTC)).astimezone(tz)
    if period is Period.TODAY:
        start_local = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
    else:  # MONTH
        start_local = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start_local.month == 12:
            end_local = start_local.replace(year=start_local.year + 1, month=1)
        else:
            end_local = start_local.replace(month=start_local.month + 1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
