"""Unit tests: analytics time-period resolution (timezone-correct, deterministic)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.analytics.periods import Period, resolve_period

_NOW = datetime(2026, 3, 15, 10, 30, tzinfo=UTC)


def test_all_period_is_unbounded() -> None:
    assert resolve_period(Period.ALL, "UTC", now=_NOW) == (None, None)


def test_today_utc() -> None:
    start, end = resolve_period(Period.TODAY, "UTC", now=_NOW)
    assert start == datetime(2026, 3, 15, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 3, 16, 0, 0, tzinfo=UTC)


def test_month_utc() -> None:
    start, end = resolve_period(Period.MONTH, "UTC", now=_NOW)
    assert start == datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 4, 1, 0, 0, tzinfo=UTC)


def test_month_december_rolls_over_year() -> None:
    dec = datetime(2026, 12, 20, 12, 0, tzinfo=UTC)
    start, end = resolve_period(Period.MONTH, "UTC", now=dec)
    assert start == datetime(2026, 12, 1, 0, 0, tzinfo=UTC)
    assert end == datetime(2027, 1, 1, 0, 0, tzinfo=UTC)


def test_today_in_non_utc_timezone_converts_to_utc() -> None:
    # Asia/Kolkata is UTC+5:30; 2026-03-15 10:30 UTC is 16:00 local, so "today"
    # local midnight is 2026-03-15 00:00 +05:30 = 2026-03-14 18:30 UTC.
    start, end = resolve_period(Period.TODAY, "Asia/Kolkata", now=_NOW)
    assert start == datetime(2026, 3, 14, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 3, 15, 18, 30, tzinfo=UTC)
