"""Unit tests: draft lifecycle transition rules (plan item 6)."""

from __future__ import annotations

from app.catalogai.models import (
    APPROVABLE_FROM,
    REGENERATABLE_FROM,
    TERMINAL,
    DraftStatus,
)


def test_only_generated_is_approvable() -> None:
    assert frozenset({DraftStatus.GENERATED}) == APPROVABLE_FROM
    for s in DraftStatus:
        approvable = s in APPROVABLE_FROM
        assert approvable == (s is DraftStatus.GENERATED)


def test_terminal_states_are_approved_and_rejected() -> None:
    assert frozenset({DraftStatus.APPROVED, DraftStatus.REJECTED}) == TERMINAL


def test_regeneratable_excludes_terminal() -> None:
    assert not (REGENERATABLE_FROM & TERMINAL)
    assert DraftStatus.FAILED in REGENERATABLE_FROM
    assert DraftStatus.GENERATED in REGENERATABLE_FROM


def test_status_values_are_stable_strings() -> None:
    assert DraftStatus.GENERATED.value == "GENERATED"
    assert DraftStatus.APPROVED.value == "APPROVED"
    assert DraftStatus.FAILED.value == "FAILED"
