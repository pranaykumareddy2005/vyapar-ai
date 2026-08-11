"""Gemini multimodal adapter - realizes :class:`AiProvider` over the Google
Generative Language REST API.

Only this file knows the vendor wire format. It is constructed by the composition
root when ``AI_PROVIDER=gemini`` and requires ``AI_API_KEY``; the rest of the
application depends solely on the :class:`AiProvider` Protocol. The adapter forces
a strict JSON response and re-validates it through :class:`AiDraftPayload`, so a
malformed or hallucinated shape becomes :class:`AiInvalidResponse` rather than a
bad draft.

Live validation status: exercised in tests via a mocked HTTP transport; a real
Gemini call has NOT been executed in this environment (no API key available).
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

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# The model is instructed to return this exact shape. Price is intentionally NOT
# requested - a price must never originate from the image.
_PROMPT = (
    "You are a retail catalog assistant. Look at the product image and return ONLY "
    "a JSON object with keys: name (string), description (string), "
    "category_suggestion (string), sku_suggestion (string), tags (array of "
    "strings), confidence (number between 0 and 1 for how confident you are). "
    "Do NOT include price or any monetary value. If a field is not reliably "
    "determinable from the image, use null (or an empty array for tags). "
    "Do not invent facts."
)

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "nullable": True},
        "description": {"type": "string", "nullable": True},
        "category_suggestion": {"type": "string", "nullable": True},
        "sku_suggestion": {"type": "string", "nullable": True},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["confidence"],
}


class GeminiAdapter:
    """Adapter over Gemini ``generateContent`` for image -> structured listing."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise AiProviderConfigError("AI_API_KEY is required for the gemini provider")
        self._api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=timeout)

    def describe(self, image: bytes, content_type: str) -> AiDraftPayload:
        if not image:
            raise AiInvalidResponse("empty image payload")

        body = {
            "contents": [
                {
                    "parts": [
                        {"text": _PROMPT},
                        {
                            "inline_data": {
                                "mime_type": content_type,
                                "data": base64.b64encode(image).decode("ascii"),
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": _RESPONSE_SCHEMA,
            },
        }
        url = f"{_BASE_URL}/{self.model}:generateContent"

        try:
            response = self._client.post(url, params={"key": self._api_key}, json=body)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AiProviderTimeout(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise AiProviderRateLimited(str(exc)) from exc
            if status in (401, 403):
                raise AiProviderConfigError(f"gemini auth failed ({status})") from exc
            raise AiProviderUnavailable(f"gemini returned {status}") from exc
        except httpx.HTTPError as exc:  # connect errors, etc.
            raise AiProviderUnavailable(str(exc)) from exc

        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> AiDraftPayload:
        try:
            envelope = response.json()
            candidates = envelope.get("candidates") or []
            if not candidates:
                raise AiInvalidResponse("gemini returned no candidates")
            parts = candidates[0].get("content", {}).get("parts") or []
            if not parts:
                raise AiInvalidResponse("gemini returned an empty candidate")
            text = parts[0].get("text", "")
            if not text:
                raise AiInvalidResponse("gemini returned empty content")
            data = json.loads(text)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AiInvalidResponse(f"could not parse gemini response: {exc}") from exc

        try:
            return AiDraftPayload.model_validate(data)
        except ValidationError as exc:
            raise AiInvalidResponse(f"gemini response failed schema validation: {exc}") from exc
