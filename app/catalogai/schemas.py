"""Pydantic schemas for the AI Catalog Generator.

``AiDraftPayload`` is the strict, application-level validation gate for anything
a provider returns: model output is never trusted merely because it parses
(plan item 12). Deliberately there is **no price field** - a price is never
inferred from an image (FR/plan item 15); the merchant supplies it during review.

The API edge never returns ORM objects; ``DraftOut`` is the response contract.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from app.catalogai.models import CatalogAiDraft

_MAX_TAGS = 20
_MAX_TAG_LEN = 50


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class AiDraftPayload(BaseModel):
    """Validated structured output from a multimodal provider.

    ``extra="ignore"`` guarantees that any unexpected key a model emits - notably
    a fabricated ``price`` - is dropped and can never reach the persisted draft.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category_suggestion: str | None = Field(default=None, max_length=100)
    sku_suggestion: str | None = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=_MAX_TAGS)
    # AI-claimed confidence in [0, 1]. Required: a provider must state how sure it
    # is so low-confidence drafts can be flagged for review (plan item 16).
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("name", "description", "category_suggestion", "sku_suggestion")
    @classmethod
    def _empty_becomes_null(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, tags: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in tags:
            norm = tag.strip()
            if not norm:
                continue
            if len(norm) > _MAX_TAG_LEN:
                raise ValueError(f"tag exceeds {_MAX_TAG_LEN} characters")
            cleaned.append(norm)
        return cleaned


class DraftEdit(BaseModel):
    """Partial merchant edit of a draft prior to (or at) approval.

    ``price`` is the merchant's own input - the only trusted source of a price.
    Only provided fields are applied.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category_id: int | None = None
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class DraftOut(BaseModel):
    """API response for a draft. Never exposes storage keys or internal columns."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    status: str
    name: str | None
    description: str | None
    category_suggestion: str | None
    category_id: int | None
    sku_suggestion: str | None
    price: Decimal | None
    tags: list[str]
    confidence: float | None
    low_confidence: bool
    ai_provider: str | None
    ai_model: str | None
    error_code: str | None
    source_image_url: str | None
    approved_product_id: int | None
    approved_by: int | None

    @classmethod
    def from_model(cls, draft: CatalogAiDraft, *, confidence_threshold: float) -> DraftOut:
        low = draft.confidence is not None and draft.confidence < confidence_threshold
        return cls(
            id=draft.id,
            business_id=draft.business_id,
            status=draft.status.value,
            name=draft.name,
            description=draft.description,
            category_suggestion=draft.category_suggestion,
            category_id=draft.category_id,
            sku_suggestion=draft.sku_suggestion,
            price=draft.price_amt,
            tags=list(draft.tags or []),
            confidence=draft.confidence,
            low_confidence=low,
            ai_provider=draft.ai_provider,
            ai_model=draft.ai_model,
            error_code=draft.error_code,
            source_image_url=draft.source_image_url,
            approved_product_id=draft.approved_product_id,
            approved_by=draft.approved_by,
        )
