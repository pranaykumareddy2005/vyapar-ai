"""Multilingual embedding client (Ollama) - scaffolding for future semantic
product search.

This is deliberately a thin, standalone client and is **not** wired into the live
product resolver yet: the current keyword resolver (via ``CatalogService``) is
sufficient for the MVP, and adding a vector store now would be infrastructure for
appearance only. The client is provided so multilingual semantic retrieval can be
built later without touching the domain layer.

Safety notes for whoever wires this up:
- Embeddings must be computed and searched **per business_id** (tenant-scoped);
  never let a query embedding match another business's products.
- Embed product *text* (name/description), never internal ids; the model output
  is a vector of floats and is used only to rank candidates that ``CatalogService``
  already scoped to the tenant. The AI never selects a record directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from app.conversation.provider import (
    ConversationAiConfigError,
    ConversationAiInvalidResponse,
    ConversationAiTimeout,
    ConversationAiUnavailable,
)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Text -> dense vector. Language-agnostic; carries no tenant/id information."""

    name: str
    model: str

    def embed(self, text: str) -> list[float]: ...


class OllamaEmbeddingClient:
    """Adapter over Ollama ``/api/embeddings`` for multilingual text embeddings."""

    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise ConversationAiConfigError("OLLAMA_BASE_URL is required for embeddings")
        if not model:
            raise ConversationAiConfigError("OLLAMA_EMBEDDING_MODEL is required for embeddings")
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._client = client or httpx.Client(timeout=timeout)

    def embed(self, text: str) -> list[float]:
        body = {"model": self.model, "prompt": text}
        url = f"{self._base_url}/api/embeddings"
        try:
            response = self._client.post(url, json=body)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ConversationAiTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ConversationAiUnavailable(str(exc)) from exc

        try:
            data = response.json()
            vector = data["embedding"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ConversationAiInvalidResponse(f"could not parse embedding: {exc}") from exc

        if not isinstance(vector, list) or not vector:
            raise ConversationAiInvalidResponse("ollama returned an empty embedding")
        return [float(x) for x in vector]
