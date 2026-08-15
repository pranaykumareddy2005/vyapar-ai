"""Unit tests: OllamaEmbeddingClient (mocked HTTP)."""

from __future__ import annotations

import httpx
import pytest
from app.conversation.embeddings import OllamaEmbeddingClient
from app.conversation.provider import (
    ConversationAiConfigError,
    ConversationAiInvalidResponse,
    ConversationAiTimeout,
    ConversationAiUnavailable,
)


def _client(handler: object) -> OllamaEmbeddingClient:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return OllamaEmbeddingClient(
        base_url="http://localhost:11434", model="mxbai-embed-large", client=client
    )


def test_embed_returns_float_vector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    vector = _client(handler).embed("notebook")
    assert vector == [0.1, 0.2, 0.3]
    assert all(isinstance(x, float) for x in vector)


def test_empty_embedding_is_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": []})

    with pytest.raises(ConversationAiInvalidResponse):
        _client(handler).embed("x")


def test_missing_embedding_key_is_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": 1})

    with pytest.raises(ConversationAiInvalidResponse):
        _client(handler).embed("x")


def test_timeout_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("t")

    with pytest.raises(ConversationAiTimeout):
        _client(handler).embed("x")


def test_connect_error_mapped_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ConversationAiUnavailable):
        _client(handler).embed("x")


def test_missing_config_rejected() -> None:
    with pytest.raises(ConversationAiConfigError):
        OllamaEmbeddingClient(base_url="", model="mxbai-embed-large")
    with pytest.raises(ConversationAiConfigError):
        OllamaEmbeddingClient(base_url="http://localhost:11434", model="")
