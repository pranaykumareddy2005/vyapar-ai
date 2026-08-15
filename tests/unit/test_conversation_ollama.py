"""Unit tests: OllamaConversationAdapter parsing & failure mapping (mocked HTTP).

No Ollama server or pulled model is required - the transport is mocked, so these
run in CI without local inference (brief items 19, 24).
"""

from __future__ import annotations

import httpx
import pytest
from app.conversation.adapters.ollama import OllamaConversationAdapter
from app.conversation.provider import (
    ConversationAiConfigError,
    ConversationAiInvalidResponse,
    ConversationAiRateLimited,
    ConversationAiTimeout,
    ConversationAiUnavailable,
)
from app.conversation.schemas import IntentType, Language, StockDirection


def _adapter(handler: object) -> OllamaConversationAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return OllamaConversationAdapter(
        base_url="http://localhost:11434", model="qwen2.5:7b", client=client
    )


def _response_handler(inner_json: str) -> object:
    """Wrap a model's JSON string in Ollama's /api/generate envelope."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": inner_json, "done": True})

    return handler


def test_success_maps_to_resolved_intent() -> None:
    adapter = _adapter(
        _response_handler(
            '{"intent": "ADJUST_STOCK", "confidence": 0.9, "language": "en", '
            '"entities": {"product_query": "notebook", "quantity": 20, '
            '"direction": "INCREASE"}}'
        )
    )
    result = adapter.resolve("add 20 notebooks")
    assert result.intent is IntentType.ADJUST_STOCK
    assert result.entities.quantity == 20
    assert result.entities.direction is StockDirection.INCREASE
    assert result.language is Language.EN


def test_telugu_response_parsed_and_language_captured() -> None:
    adapter = _adapter(
        _response_handler(
            '{"intent": "GET_STOCK", "confidence": 0.88, "language": "te", '
            '"entities": {"product_query": "notebook"}}'
        )
    )
    result = adapter.resolve("నోట్‌బుక్స్ ఎన్ని ఉన్నాయి?")
    assert result.intent is IntentType.GET_STOCK
    assert result.language is Language.TE


def test_unknown_language_falls_back_to_english() -> None:
    adapter = _adapter(
        _response_handler(
            '{"intent": "GET_STOCK", "confidence": 0.7, "language": "Klingon", '
            '"entities": {"product_query": "pen"}}'
        )
    )
    assert adapter.resolve("pen stock").language is Language.EN


def test_foreign_keys_in_response_are_ignored() -> None:
    adapter = _adapter(
        _response_handler(
            '{"intent": "GET_STOCK", "confidence": 0.9, '
            '"entities": {"product_query": "pen", "business_id": 99, "product_id": 7, '
            '"sql": "DROP TABLE inventory"}}'
        )
    )
    result = adapter.resolve("stock of pen")
    dumped = result.entities.model_dump()
    assert "business_id" not in dumped
    assert "product_id" not in dumped
    assert "sql" not in dumped


def test_malformed_json_is_invalid_response() -> None:
    with pytest.raises(ConversationAiInvalidResponse):
        _adapter(_response_handler("not json at all")).resolve("hi")


def test_empty_response_is_invalid_response() -> None:
    with pytest.raises(ConversationAiInvalidResponse):
        _adapter(_response_handler("")).resolve("hi")


def test_schema_violation_is_invalid_response() -> None:
    with pytest.raises(ConversationAiInvalidResponse):
        _adapter(_response_handler('{"confidence": 0.5}')).resolve("hi")  # missing intent


def test_out_of_range_confidence_is_invalid_response() -> None:
    with pytest.raises(ConversationAiInvalidResponse):
        _adapter(_response_handler('{"intent": "GET_STOCK", "confidence": 5}')).resolve("hi")


def test_rate_limit_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    with pytest.raises(ConversationAiRateLimited):
        _adapter(handler).resolve("hi")


def test_model_not_found_is_config_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(ConversationAiConfigError):
        _adapter(handler).resolve("hi")


def test_server_error_mapped_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    with pytest.raises(ConversationAiUnavailable):
        _adapter(handler).resolve("hi")


def test_connect_error_mapped_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ConversationAiUnavailable):
        _adapter(handler).resolve("hi")


def test_timeout_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("t")

    with pytest.raises(ConversationAiTimeout):
        _adapter(handler).resolve("hi")


def test_missing_base_url_rejected() -> None:
    with pytest.raises(ConversationAiConfigError):
        OllamaConversationAdapter(base_url="", model="qwen2.5:7b")


def test_missing_model_rejected() -> None:
    with pytest.raises(ConversationAiConfigError):
        OllamaConversationAdapter(base_url="http://localhost:11434", model="")


def test_request_targets_generate_endpoint_with_format() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        import json as _json

        seen["body"] = _json.loads(request.content)
        return httpx.Response(
            200, json={"response": '{"intent": "UNSUPPORTED", "confidence": 0.9}'}
        )

    _adapter(handler).resolve("make an order")
    assert seen["url"] == "http://localhost:11434/api/generate"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0}
    assert "format" in body  # structured output requested
