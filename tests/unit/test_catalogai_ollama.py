"""Unit tests: catalog OllamaAdapter parsing & failure mapping (mocked HTTP)."""

from __future__ import annotations

import httpx
import pytest
from app.catalogai.adapters.ollama import OllamaAdapter
from app.catalogai.provider import (
    AiInvalidResponse,
    AiProviderConfigError,
    AiProviderRateLimited,
    AiProviderTimeout,
    AiProviderUnavailable,
)


def _adapter(handler: object) -> OllamaAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return OllamaAdapter(base_url="http://localhost:11434", model="qwen2.5vl:3b", client=client)


def _response_handler(inner_json: str) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": inner_json, "done": True})

    return handler


def test_success_maps_to_draft_payload() -> None:
    adapter = _adapter(
        _response_handler(
            '{"name": "Blue Pen", "description": "A ballpoint pen.", '
            '"category_suggestion": "Stationery", "sku_suggestion": "PEN-1", '
            '"tags": ["pen", "blue"], "confidence": 0.82}'
        )
    )
    payload = adapter.describe(b"\x89PNG-bytes", "image/png")
    assert payload.name == "Blue Pen"
    assert payload.confidence == 0.82


def test_price_from_model_is_dropped() -> None:
    adapter = _adapter(_response_handler('{"name": "Pen", "price": 999, "confidence": 0.7}'))
    payload = adapter.describe(b"img", "image/png")
    assert not hasattr(payload, "price")
    assert "price" not in payload.model_dump()


def test_empty_image_rejected_without_http_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("adapter must not call the model for an empty image")

    with pytest.raises(AiInvalidResponse):
        _adapter(handler).describe(b"", "image/png")


def test_malformed_json_is_invalid_response() -> None:
    with pytest.raises(AiInvalidResponse):
        _adapter(_response_handler("not json")).describe(b"img", "image/png")


def test_schema_violation_is_invalid_response() -> None:
    # Missing required confidence.
    with pytest.raises(AiInvalidResponse):
        _adapter(_response_handler('{"name": "Pen"}')).describe(b"img", "image/png")


def test_rate_limit_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    with pytest.raises(AiProviderRateLimited):
        _adapter(handler).describe(b"img", "image/png")


def test_model_not_found_is_config_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(AiProviderConfigError):
        _adapter(handler).describe(b"img", "image/png")


def test_server_error_mapped_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    with pytest.raises(AiProviderUnavailable):
        _adapter(handler).describe(b"img", "image/png")


def test_timeout_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("t")

    with pytest.raises(AiProviderTimeout):
        _adapter(handler).describe(b"img", "image/png")


def test_missing_base_url_rejected() -> None:
    with pytest.raises(AiProviderConfigError):
        OllamaAdapter(base_url="", model="qwen2.5vl:3b")


def test_image_is_sent_base64_in_images_field() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"response": '{"confidence": 0.5}'})

    _adapter(handler).describe(b"rawbytes", "image/png")
    body = seen["body"]
    assert isinstance(body, dict)
    assert isinstance(body["images"], list) and body["images"]
    assert "price" not in body["prompt"].lower() or "do not include price" in body["prompt"].lower()
