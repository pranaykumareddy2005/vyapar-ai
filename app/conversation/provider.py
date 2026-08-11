"""Conversation AI provider abstraction + deterministic mock.

The domain depends only on the :class:`ConversationAiProvider` protocol - never on
a vendor SDK. :class:`MockConversationAiProvider` is a deterministic rule parser
(no randomness) used in dev/tests; ``GeminiConversationAdapter`` realizes the same
protocol over the real API. Provider failures are an explicit exception hierarchy
so the service can turn them into controlled user-facing replies (plan item 21).
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from app.conversation.schemas import (
    IntentEntities,
    IntentType,
    ResolvedIntent,
    StockDirection,
)
from app.inventory.models import MovementType


class ConversationAiError(Exception):
    """Base class for conversation-AI provider failures (infrastructure)."""

    code = "conversation_ai_error"


class ConversationAiTimeout(ConversationAiError):
    code = "conversation_ai_timeout"


class ConversationAiUnavailable(ConversationAiError):
    code = "conversation_ai_unavailable"


class ConversationAiRateLimited(ConversationAiError):
    code = "conversation_ai_rate_limited"


class ConversationAiConfigError(ConversationAiError):
    code = "conversation_ai_config_error"


class ConversationAiInvalidResponse(ConversationAiError):
    code = "conversation_ai_invalid_response"


@runtime_checkable
class ConversationAiProvider(Protocol):
    """Text -> validated :class:`ResolvedIntent`. Never returns tenant/authority."""

    name: str
    model: str

    def resolve(self, text: str) -> ResolvedIntent: ...


# --- deterministic mock -----------------------------------------------------

_INJECTION_KW = (
    "ignore previous",
    "ignore all",
    "disregard",
    "delete",
    "drop table",
    "truncate",
    "select *",
    " sql",
    "business_id",
    "another business",
    "other business",
    "system prompt",
)
_UNSUPPORTED_KW = (
    "order",
    "customer",
    "payment",
    "invoice",
    "refund",
    "checkout",
    "cart",
    "delivery",
    "notification",
    "dashboard",
    "analytics",
)
_INCREASE_KW = ("add", "restock", "increase", "refill", "top up")
_DECREASE_KW = ("remove", "reduce", "decrease", "subtract", "sell", "damage")
_STOCK_KW = ("how many", "stock", "left", "in stock", "quantity of", "how much")
_SEARCH_KW = ("show", "find", "search", "do we have", "look for", "list", "have we")

_STOP = {
    "add",
    "remove",
    "restock",
    "increase",
    "decrease",
    "reduce",
    "subtract",
    "sell",
    "refill",
    "damaged",
    "damage",
    "some",
    "the",
    "a",
    "an",
    "of",
    "by",
    "to",
    "for",
    "units",
    "unit",
    "how",
    "many",
    "much",
    "left",
    "in",
    "stock",
    "do",
    "we",
    "have",
    "show",
    "find",
    "search",
    "list",
    "me",
    "my",
    "please",
    "check",
    "quantity",
    "is",
    "are",
    "there",
    "got",
    "look",
    "and",
    "with",
    "currently",
    "current",
    "up",
    "top",
}


class MockConversationAiProvider:
    """Deterministic keyword rule engine. Same interface as the real adapter."""

    name = "mock"
    model = "mock-conv-1"

    def resolve(self, text: str) -> ResolvedIntent:
        raw = text.strip()
        low = raw.lower()

        if any(kw in low for kw in _INJECTION_KW) or any(kw in low for kw in _UNSUPPORTED_KW):
            return ResolvedIntent(intent=IntentType.UNSUPPORTED, confidence=0.95)

        if "do something" in low or low in {"help", "hi", "hello"}:
            return ResolvedIntent(
                intent=IntentType.CLARIFICATION_REQUIRED,
                confidence=0.5,
                clarification=(
                    "Would you like to search products, check stock, or adjust inventory?"
                ),
            )

        increase = any(kw in low for kw in _INCREASE_KW)
        decrease = any(kw in low for kw in _DECREASE_KW)
        if increase or decrease:
            direction = StockDirection.INCREASE if increase else StockDirection.DECREASE
            movement = MovementType.DAMAGE if "damage" in low else None
            quantity = self._first_int(low)
            product = self._extract_product(low)
            confidence = 0.42 if "some" in low.split() else 0.9
            return ResolvedIntent(
                intent=IntentType.ADJUST_STOCK,
                confidence=confidence,
                entities=IntentEntities(
                    product_query=product,
                    quantity=quantity,
                    direction=direction,
                    movement_type=movement,
                ),
            )

        if any(kw in low for kw in _STOCK_KW):
            return ResolvedIntent(
                intent=IntentType.GET_STOCK,
                confidence=0.9,
                entities=IntentEntities(product_query=self._extract_product(low)),
            )

        if any(kw in low for kw in _SEARCH_KW):
            return ResolvedIntent(
                intent=IntentType.SEARCH_PRODUCT,
                confidence=0.9,
                entities=IntentEntities(product_query=self._extract_product(low)),
            )

        return ResolvedIntent(
            intent=IntentType.CLARIFICATION_REQUIRED,
            confidence=0.5,
            clarification=(
                "I can search products, check stock, or adjust inventory. What would you like?"
            ),
        )

    @staticmethod
    def _first_int(text: str) -> int | None:
        match = re.search(r"\d+", text)
        return int(match.group()) if match else None

    @staticmethod
    def _extract_product(text: str) -> str | None:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        words = [t for t in tokens if t not in _STOP and not t.isdigit()]
        return " ".join(words) or None
