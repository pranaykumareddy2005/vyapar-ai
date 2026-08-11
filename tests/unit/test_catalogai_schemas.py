"""Unit tests: strict validation of AI structured output (plan items 5, 12, 15)."""

from __future__ import annotations

import pytest
from app.catalogai.schemas import AiDraftPayload, DraftOut
from pydantic import ValidationError


def test_valid_payload_parses() -> None:
    p = AiDraftPayload(
        name="Tea",
        description="Green tea",
        category_suggestion="Beverages",
        sku_suggestion="TEA-1",
        tags=["tea", "green"],
        confidence=0.8,
    )
    assert p.name == "Tea"
    assert p.tags == ["tea", "green"]


def test_confidence_is_required() -> None:
    with pytest.raises(ValidationError):
        AiDraftPayload(name="Tea")  # type: ignore[call-arg]


def test_confidence_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        AiDraftPayload(confidence=1.5)
    with pytest.raises(ValidationError):
        AiDraftPayload(confidence=-0.1)


def test_name_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        AiDraftPayload(name="x" * 201, confidence=0.5)


def test_wrong_type_rejected() -> None:
    with pytest.raises(ValidationError):
        AiDraftPayload(tags="notalist", confidence=0.5)  # type: ignore[arg-type]


def test_price_is_never_accepted_from_model() -> None:
    # A fabricated price key is silently ignored - it can never reach a draft.
    p = AiDraftPayload.model_validate(
        {"name": "Rice", "confidence": 0.9, "price": 199, "price_amt": "500.00"}
    )
    assert not hasattr(p, "price")
    assert "price" not in p.model_dump()


def test_blank_strings_become_null() -> None:
    p = AiDraftPayload(name="   ", category_suggestion="", confidence=0.7)
    assert p.name is None
    assert p.category_suggestion is None


def test_blank_and_overlong_tags_handled() -> None:
    p = AiDraftPayload(tags=["  ok  ", "   "], confidence=0.6)
    assert p.tags == ["ok"]
    with pytest.raises(ValidationError):
        AiDraftPayload(tags=["x" * 51], confidence=0.6)


def test_too_many_tags_rejected() -> None:
    with pytest.raises(ValidationError):
        AiDraftPayload(tags=[f"t{i}" for i in range(21)], confidence=0.6)


class _FakeDraft:
    """Minimal stand-in with the attributes DraftOut.from_model reads."""

    def __init__(self, confidence: float | None) -> None:
        from app.catalogai.models import DraftStatus

        self.id = 1
        self.business_id = 1
        self.status = DraftStatus.GENERATED
        self.name = "n"
        self.description = None
        self.category_suggestion = None
        self.category_id = None
        self.sku_suggestion = None
        self.price_amt = None
        self.tags = None
        self.confidence = confidence
        self.ai_provider = "mock"
        self.ai_model = "mock-1"
        self.error_code = None
        self.source_image_url = None
        self.approved_product_id = None
        self.approved_by = None


def test_low_confidence_flag_marks_uncertainty() -> None:
    low = DraftOut.from_model(_FakeDraft(0.3), confidence_threshold=0.6)  # type: ignore[arg-type]
    high = DraftOut.from_model(_FakeDraft(0.9), confidence_threshold=0.6)  # type: ignore[arg-type]
    none = DraftOut.from_model(_FakeDraft(None), confidence_threshold=0.6)  # type: ignore[arg-type]
    assert low.low_confidence is True
    assert high.low_confidence is False
    assert none.low_confidence is False
