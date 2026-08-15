"""Ollama multimodal adapter - realizes :class:`AiProvider` over a local Ollama
vision model.

Only this file knows the Ollama wire format. It is constructed by the composition
root when ``AI_PROVIDER=ollama``; the rest of the application depends solely on
the :class:`AiProvider` Protocol. The adapter forces a strict JSON response via
Ollama's structured ``format`` and re-validates it through :class:`AiDraftPayload`,
so a malformed or hallucinated shape becomes :class:`AiInvalidResponse` rather than
a bad draft.

Price is intentionally NOT requested and ``AiDraftPayload`` drops any monetary key
the model emits: a price must never originate from an image (the merchant supplies
it during review).
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.catalogai.provider import (
    AiInvalidResponse,
    AiProviderConfigError,
    AiProviderRateLimited,
    AiProviderTimeout,
    AiProviderUnavailable,
)
from app.catalogai.schemas import AiDraftPayload

_PROMPT = (
    "You are a retail catalog assistant. Look at the product image and return ONLY "
    "a JSON object (no prose, no markdown) with keys: name (string), description "
    "(string), category_suggestion (string), sku_suggestion (string), tags (array "
    "of strings), confidence (number between 0 and 1 for how confident you are). "
    "Do NOT include price or any monetary value. If a field is not reliably "
    "determinable from the image, use null (or an empty array for tags). Do not "
    "invent facts."
)

_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "category_suggestion": {"type": ["string", "null"]},
        "sku_suggestion": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["confidence"],
}


class OllamaAdapter:
    """Adapter over Ollama ``/api/generate`` for image -> structured listing."""

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
            raise AiProviderConfigError("OLLAMA_BASE_URL is required for the ollama provider")
        if not model:
            raise AiProviderConfigError("OLLAMA_CATALOG_MODEL is required for the ollama provider")
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._client = client or httpx.Client(timeout=timeout)

    def describe(self, image: bytes, content_type: str) -> AiDraftPayload:
        if not image:
            raise AiInvalidResponse("empty image payload")

        body = {
            "model": self.model,
            "prompt": _PROMPT,
            "images": [base64.b64encode(image).decode("ascii")],
            "format": _FORMAT_SCHEMA,
            "stream": False,
            "options": {"temperature": 0},
        }
        url = f"{self._base_url}/api/generate"

        try:
            response = self._client.post(url, json=body)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AiProviderTimeout(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise AiProviderRateLimited(str(exc)) from exc
            if status == 404:
                raise AiProviderConfigError(
                    f"ollama model '{self.model}' not found (pull it first)"
                ) from exc
            raise AiProviderUnavailable(f"ollama returned {status}") from exc
        except httpx.HTTPError as exc:
            raise AiProviderUnavailable(str(exc)) from exc

        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> AiDraftPayload:
        try:
            envelope = response.json()
            text = envelope.get("response", "")
            if not text or not str(text).strip():
                raise AiInvalidResponse("ollama returned empty content")
            data = json.loads(text)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AiInvalidResponse(f"could not parse ollama response: {exc}") from exc

        try:
            return AiDraftPayload.model_validate(data)
        except ValidationError as exc:
            raise AiInvalidResponse(f"ollama response failed schema validation: {exc}") from exc
