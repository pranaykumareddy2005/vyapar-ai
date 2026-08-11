from __future__ import annotations

from app.config import Settings


def test_confidence_threshold_default_is_dev_value() -> None:
    assert Settings().ai_confidence_threshold == 0.6


def test_tax_rate_default_is_zero_not_gst() -> None:
    # Per plan item 10: no hard-coded GST assumption.
    assert Settings().default_tax_rate == 0.0


def test_is_production_flag() -> None:
    assert Settings(environment="production").is_production
    assert not Settings(environment="development").is_production
