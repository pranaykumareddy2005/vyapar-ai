"""Unit tests: GeminiConversationAdapter parsing & failure mapping (mocked HTTP).

No real API key is required (plan items 23, 24).
"""

from __future__ import annotations

import httpx
import pytest
from app.conversation.adapters.gemini import GeminiConversationAdapter
from app.conversation.provider import (
    ConversationAiConfigError,
    ConversationAiInvalidResponse,
    ConversationAiRateLimited,
    ConversationAiTimeout,
    ConversationAiUnavailable,
)
from app.conversation.schemas import IntentType


def _adapter(handler: object) -> GeminiConversationAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return GeminiConversationAdapter(api_key="k", model="gemini-1.5-flash", client=client)


def _json_handler(payload: str) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": payload}]}}]}
        )

    return handler


def test_success_maps_to_resolved_intent() -> None:
    adapter = _adapter(
        _json_handler(
            '{"intent": "ADJUST_STOCK", "confidence": 0.8, '
            '"entities": {"product_query": "notebook", "quantity": 20, '
            '"direction": "INCREASE"}}'
        )
    )
    result = adapter.resolve("add 20 notebooks")
    assert result.intent is IntentType.ADJUST_STOCK
    assert result.entities.quantity == 20


def test_foreign_keys_in_response_are_ignored() -> None:
    adapter = _adapter(
        _json_handler(
            '{"intent": "GET_STOCK", "confidence": 0.9, '
            '"entities": {"product_query": "pen", "business_id": 99, "product_id": 7}}'
        )
    )
    result = adapter.resolve("stock of pen")
    dumped = result.entities.model_dump()
    assert "business_id" not in dumped and "product_id" not in dumped


def test_malformed_json_is_invalid_response() -> None:
    with pytest.raises(ConversationAiInvalidResponse):
        _adapter(_json_handler("not json")).resolve("hi")


def test_schema_violation_is_invalid_response() -> None:
    with pytest.raises(ConversationAiInvalidResponse):
        _adapter(_json_handler('{"confidence": 0.5}')).resolve("hi")  # missing intent


def test_empty_candidates_is_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    with pytest.raises(ConversationAiInvalidResponse):
        _adapter(handler).resolve("hi")


def test_rate_limit_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    with pytest.raises(ConversationAiRateLimited):
        _adapter(handler).resolve("hi")


def test_auth_error_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={})

    with pytest.raises(ConversationAiConfigError):
        _adapter(handler).resolve("hi")


def test_server_error_mapped_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    with pytest.raises(ConversationAiUnavailable):
        _adapter(handler).resolve("hi")


def test_timeout_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("t")

    with pytest.raises(ConversationAiTimeout):
        _adapter(handler).resolve("hi")


def test_missing_api_key_rejected() -> None:
    with pytest.raises(ConversationAiConfigError):
        GeminiConversationAdapter(api_key="", model="gemini-1.5-flash")
