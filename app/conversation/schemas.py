"""Schemas for the conversational layer.

``ResolvedIntent`` is the strict, validated structure the AI must return - the
only mechanism by which an operation is selected. It carries NO ``business_id``
and NO trusted ``product_id``: tenant comes from the authenticated principal and
products are resolved by text through ``CatalogService`` (plan items 3, 9, 10, 33).
``extra="ignore"`` guarantees any extra key a model emits (a fabricated
``business_id``, ``product_id``, SQL, etc.) is dropped before it can reach a
handler.
"""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.inventory.models import MovementType

_MAX_QTY = 1_000_000


class IntentType(enum.StrEnum):
    SEARCH_PRODUCT = "SEARCH_PRODUCT"
    GET_STOCK = "GET_STOCK"
    ADJUST_STOCK = "ADJUST_STOCK"
    UNSUPPORTED = "UNSUPPORTED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


class StockDirection(enum.StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class Language(enum.StrEnum):
    """Languages the conversational layer understands and can reply in.

    Language is metadata only: it never changes which business operation runs or
    which record is touched. The database and domain models stay language-neutral.
    """

    EN = "en"
    TE = "te"
    HI = "hi"


class IntentEntities(BaseModel):
    """Entities extracted by the AI. Intentionally has no id/tenant fields."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    product_query: str | None = Field(default=None, max_length=200)
    quantity: int | None = Field(default=None)
    direction: StockDirection | None = None
    movement_type: MovementType | None = None

    @field_validator("product_query")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("quantity")
    @classmethod
    def _sane_quantity(cls, value: int | None) -> int | None:
        # Treat non-positive or absurd quantities as "not provided" so the handler
        # asks for clarification rather than acting on nonsense.
        if value is None or value <= 0 or value > _MAX_QTY:
            return None
        return value

    @field_validator("movement_type", mode="before")
    @classmethod
    def _tolerate_unknown_movement(cls, value: Any) -> Any:
        # An unrecognized movement type from the model becomes None; the handler
        # then derives a valid type from the direction (plan item 27).
        if value is None:
            return None
        try:
            return MovementType(value)
        except ValueError:
            return None


class ResolvedIntent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: IntentEntities = Field(default_factory=IntentEntities)
    # Optional clarification prompt the model may supply; never chain-of-thought.
    clarification: str | None = Field(default=None, max_length=500)
    # The language the model believes the user wrote in. Informational only: the
    # authoritative reply language is derived from the user's text (see
    # ``app.conversation.language``), so a spoofed value cannot change behaviour.
    language: Language = Language.EN

    @field_validator("language", mode="before")
    @classmethod
    def _tolerate_unknown_language(cls, value: Any) -> Any:
        # A model may emit "English", "en-IN", None, etc. Anything unrecognised
        # falls back to EN rather than failing validation.
        if value is None:
            return Language.EN
        if isinstance(value, Language):
            return value
        text = str(value).strip().lower()
        aliases = {
            "en": Language.EN,
            "eng": Language.EN,
            "english": Language.EN,
            "te": Language.TE,
            "tel": Language.TE,
            "telugu": Language.TE,
            "hi": Language.HI,
            "hin": Language.HI,
            "hindi": Language.HI,
        }
        # Handle region tags like "en-IN" / "hi_IN".
        base = text.replace("_", "-").split("-", 1)[0]
        return aliases.get(text) or aliases.get(base) or Language.EN


# --- API edge ---------------------------------------------------------------


class ConversationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    message_id: str = Field(default="conv-msg", max_length=128)
    sender_phone: str = Field(default="dashboard", min_length=1, max_length=32)


class ConversationReply(BaseModel):
    reply: str
    intent: str | None
    outcome: str
    provider_message_id: str
