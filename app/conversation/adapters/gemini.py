"""Gemini conversation adapter - realizes :class:`ConversationAiProvider`.

Only this file knows the vendor wire format. It forces a strict JSON response and
re-validates it through :class:`ResolvedIntent`, so a malformed or hallucinated
shape becomes :class:`ConversationAiInvalidResponse` rather than an unsafe intent.
The prompt asks only for intent + entities + confidence; the model is never asked
for (and could never supply) a ``business_id`` or database id that reaches a
handler.

Live validation status: exercised via a mocked HTTP transport; a real Gemini call
has NOT been executed in this environment (no API key available).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.conversation.provider import (
    ConversationAiConfigError,
    ConversationAiInvalidResponse,
    ConversationAiRateLimited,
    ConversationAiTimeout,
    ConversationAiUnavailable,
)
from app.conversation.schemas import ResolvedIntent

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

_PROMPT = (
    "You are the intent classifier for a shop's inventory assistant. Classify the "
    "merchant's message and return ONLY JSON with keys: intent (one of "
    "SEARCH_PRODUCT, GET_STOCK, ADJUST_STOCK, UNSUPPORTED, CLARIFICATION_REQUIRED), "
    "confidence (0..1), entities {product_query (string|null), quantity "
    "(integer|null), direction (INCREASE|DECREASE|null), movement_type "
    "(RESTOCK|SALE|MANUAL_ADJUSTMENT|DAMAGE|null)}, clarification (string|null). "
    "Do NOT include business, ids, SQL, or code. Do not invent products. If the "
    "request is about orders, customers, payments, or invoices, return UNSUPPORTED."
)

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "confidence": {"type": "number"},
        "entities": {
            "type": "object",
            "properties": {
                "product_query": {"type": "string", "nullable": True},
                "quantity": {"type": "integer", "nullable": True},
                "direction": {"type": "string", "nullable": True},
                "movement_type": {"type": "string", "nullable": True},
            },
        },
        "clarification": {"type": "string", "nullable": True},
    },
    "required": ["intent", "confidence"],
}


class GeminiConversationAdapter:
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
            raise ConversationAiConfigError("AI_API_KEY is required for the gemini provider")
        self._api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=timeout)

    def resolve(self, text: str) -> ResolvedIntent:
        body = {
            "contents": [{"parts": [{"text": _PROMPT}, {"text": f"Message: {text}"}]}],
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
            raise ConversationAiTimeout(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise ConversationAiRateLimited(str(exc)) from exc
            if status in (401, 403):
                raise ConversationAiConfigError(f"gemini auth failed ({status})") from exc
            raise ConversationAiUnavailable(f"gemini returned {status}") from exc
        except httpx.HTTPError as exc:
            raise ConversationAiUnavailable(str(exc)) from exc
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> ResolvedIntent:
        try:
            envelope = response.json()
            candidates = envelope.get("candidates") or []
            if not candidates:
                raise ConversationAiInvalidResponse("gemini returned no candidates")
            parts = candidates[0].get("content", {}).get("parts") or []
            if not parts:
                raise ConversationAiInvalidResponse("gemini returned an empty candidate")
            payload = parts[0].get("text", "")
            if not payload:
                raise ConversationAiInvalidResponse("gemini returned empty content")
            data = json.loads(payload)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ConversationAiInvalidResponse(f"could not parse gemini response: {exc}") from exc

        try:
            return ResolvedIntent.model_validate(data)
        except ValidationError as exc:
            raise ConversationAiInvalidResponse(
                f"gemini response failed schema validation: {exc}"
            ) from exc
