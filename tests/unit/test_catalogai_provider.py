"""Unit tests: AI provider abstraction, GeminiAdapter parsing, and factory.

The provider layer is tested independently of the catalogai business logic and
NEVER requires a real API key (plan items 21, 23) - the Gemini adapter is driven
through a mocked HTTP transport.
"""

from __future__ import annotations

import httpx
import pytest
from app.catalogai.adapters.gemini import GeminiAdapter
from app.catalogai.provider import (
    AiInvalidResponse,
    AiProviderConfigError,
    AiProviderRateLimited,
    AiProviderTimeout,
    AiProviderUnavailable,
    MockAiProvider,
)
from app.config import Settings
from app.providers import build_ai_provider

# --- MockAiProvider ---------------------------------------------------------


def test_mock_provider_is_deterministic() -> None:
    provider = MockAiProvider()
    a = provider.describe(b"bytes", "image/jpeg")
    b = provider.describe(b"other", "image/png")
    assert a.model_dump() == b.model_dump()
    assert a.name == "Sample Product"
    assert a.confidence == 0.9
    # The mock never returns a price.
    assert "price" not in a.model_dump()


def test_mock_provider_rejects_empty_image() -> None:
    with pytest.raises(AiInvalidResponse):
        MockAiProvider().describe(b"", "image/jpeg")


def test_mock_provider_confidence_is_configurable() -> None:
    assert MockAiProvider(confidence=0.2).describe(b"x", "image/jpeg").confidence == 0.2


# --- GeminiAdapter (mocked transport) --------------------------------------


def _gemini(handler: object) -> GeminiAdapter:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.Client(transport=transport)
    return GeminiAdapter(api_key="test-key", model="gemini-1.5-flash", client=client)


def _gemini_json(payload: str) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": payload}]}}]},
        )

    return handler


def test_gemini_success_maps_to_payload() -> None:
    adapter = _gemini(_gemini_json('{"name": "Soap", "confidence": 0.7, "tags": ["clean"]}'))
    result = adapter.describe(b"img", "image/jpeg")
    assert result.name == "Soap"
    assert result.confidence == 0.7
    assert result.tags == ["clean"]


def test_gemini_ignores_hallucinated_price() -> None:
    adapter = _gemini(_gemini_json('{"name": "Soap", "confidence": 0.7, "price": 99}'))
    result = adapter.describe(b"img", "image/jpeg")
    assert "price" not in result.model_dump()


def test_gemini_malformed_json_is_invalid_response() -> None:
    adapter = _gemini(_gemini_json("not-json"))
    with pytest.raises(AiInvalidResponse):
        adapter.describe(b"img", "image/jpeg")


def test_gemini_schema_violation_is_invalid_response() -> None:
    # Missing required "confidence".
    adapter = _gemini(_gemini_json('{"name": "Soap"}'))
    with pytest.raises(AiInvalidResponse):
        adapter.describe(b"img", "image/jpeg")


def test_gemini_empty_candidates_is_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    with pytest.raises(AiInvalidResponse):
        _gemini(handler).describe(b"img", "image/jpeg")


def test_gemini_rate_limit_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate"})

    with pytest.raises(AiProviderRateLimited):
        _gemini(handler).describe(b"img", "image/jpeg")


def test_gemini_auth_error_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(AiProviderConfigError):
        _gemini(handler).describe(b"img", "image/jpeg")


def test_gemini_server_error_mapped_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    with pytest.raises(AiProviderUnavailable):
        _gemini(handler).describe(b"img", "image/jpeg")


def test_gemini_timeout_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(AiProviderTimeout):
        _gemini(handler).describe(b"img", "image/jpeg")


def test_gemini_requires_api_key() -> None:
    with pytest.raises(AiProviderConfigError):
        GeminiAdapter(api_key="", model="gemini-1.5-flash")


# --- factory (build_ai_provider) -------------------------------------------


def test_factory_selects_mock_in_development() -> None:
    provider = build_ai_provider(Settings(ai_provider="mock", environment="development"))
    assert isinstance(provider, MockAiProvider)


def test_factory_rejects_mock_in_production() -> None:
    with pytest.raises(AiProviderConfigError):
        build_ai_provider(Settings(ai_provider="mock", environment="production"))


def test_factory_gemini_requires_key() -> None:
    with pytest.raises(AiProviderConfigError):
        build_ai_provider(Settings(ai_provider="gemini", ai_api_key="", environment="development"))
