"""Meta WhatsApp Cloud API adapter - realizes :class:`MessagingProvider`.

Only this file knows Meta's outbound wire format (the ``/messages`` and ``/media``
Graph API endpoints, Bearer auth, message envelopes). It translates the neutral
:class:`OutgoingMessage` into a Meta payload and returns a :class:`SendResult`; it
contains NO business logic (no inventory/order/payment/catalogue rules).

Secret hygiene: the access token is only ever placed in the ``Authorization``
header on the client and is never included in exception messages or logs. Errors
map to a neutral hierarchy so callers can degrade gracefully.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.common.messaging import OutgoingMessage, SendResult

# Transient HTTP statuses worth retrying (rate-limit + gateway/server errors).
_RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class MetaWhatsAppError(Exception):
    """Base class for Meta provider failures (infrastructure)."""

    code = "whatsapp_error"


class MetaWhatsAppTimeout(MetaWhatsAppError):
    code = "whatsapp_timeout"


class MetaWhatsAppUnavailable(MetaWhatsAppError):
    code = "whatsapp_unavailable"


class MetaWhatsAppRateLimited(MetaWhatsAppError):
    code = "whatsapp_rate_limited"


class MetaWhatsAppConfigError(MetaWhatsAppError):
    code = "whatsapp_config_error"


class MetaWhatsAppInvalidRecipient(MetaWhatsAppError):
    code = "whatsapp_invalid_recipient"


class MetaWhatsAppInvalidResponse(MetaWhatsAppError):
    code = "whatsapp_invalid_response"


class MetaWhatsAppProvider:
    """Adapter over the Meta WhatsApp Cloud API implementing ``MessagingProvider``."""

    name = "meta"

    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        api_base: str = "https://graph.facebook.com",
        api_version: str = "v21.0",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
        template_language: str = "en",
        max_retries: int = 3,
        backoff_base: float = 0.6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not access_token:
            raise MetaWhatsAppConfigError("WA_API_TOKEN is required for the meta provider")
        if not phone_number_id:
            raise MetaWhatsAppConfigError("WA_PHONE_NUMBER_ID is required for the meta provider")
        self._phone_number_id = phone_number_id
        self._base = f"{api_base.rstrip('/')}/{api_version.strip('/')}"
        self._template_language = template_language
        # Bounded retry with linear backoff for transient failures. Injectable
        # ``sleep`` keeps tests fast.
        self._max_retries = max(1, max_retries)
        self._backoff_base = backoff_base
        self._sleep = sleep
        # The token lives only here, on the client's default headers.
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    # --- outbound (MessagingProvider protocol) ----------------------------

    def send(self, message: OutgoingMessage) -> SendResult:
        """Send a text (or, if ``template_name`` is set, a template) message."""
        if message.template_name:
            payload: dict[str, Any] = {
                "type": "template",
                "template": {
                    "name": message.template_name,
                    "language": {"code": self._template_language},
                },
            }
        else:
            payload = {"type": "text", "text": {"preview_url": False, "body": message.text}}
        return self._send_message(message.recipient_phone, payload)

    def send_document(
        self, recipient_phone: str, *, media_id: str, filename: str, caption: str | None = None
    ) -> SendResult:
        """Send a previously uploaded document (e.g. an invoice PDF) by media id."""
        document: dict[str, Any] = {"id": media_id, "filename": filename}
        if caption:
            document["caption"] = caption
        return self._send_message(recipient_phone, {"type": "document", "document": document})

    def send_image(
        self, recipient_phone: str, *, media_id: str, caption: str | None = None
    ) -> SendResult:
        image: dict[str, Any] = {"id": media_id}
        if caption:
            image["caption"] = caption
        return self._send_message(recipient_phone, {"type": "image", "image": image})

    def send_buttons(
        self,
        recipient_phone: str,
        *,
        body: str,
        buttons: list[tuple[str, str]],
        header: str | None = None,
    ) -> SendResult:
        """Send up to 3 reply buttons. ``buttons`` = list of (id, title).

        The button ids are the deterministic interaction ids the router dispatches
        on; Meta echoes them back verbatim on tap.
        """
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid[:256], "title": title[:20]}}
                    for bid, title in buttons[:3]
                ]
            },
        }
        if header:
            interactive["header"] = {"type": "text", "text": header[:60]}
        return self._send_message(
            recipient_phone, {"type": "interactive", "interactive": interactive}
        )

    def send_list(
        self,
        recipient_phone: str,
        *,
        body: str,
        button_text: str,
        rows: list[tuple[str, str, str | None]],
        header: str | None = None,
        section_title: str = "Options",
    ) -> SendResult:
        """Send a list menu (up to 10 rows). ``rows`` = list of (id, title, desc)."""
        interactive: dict[str, Any] = {
            "type": "list",
            "body": {"text": body[:1024]},
            "action": {
                "button": button_text[:20],
                "sections": [
                    {
                        "title": section_title[:24],
                        "rows": [
                            {
                                "id": rid[:200],
                                "title": title[:24],
                                "description": (desc or "")[:72],
                            }
                            for rid, title, desc in rows[:10]
                        ],
                    }
                ],
            },
        }
        if header:
            interactive["header"] = {"type": "text", "text": header[:60]}
        return self._send_message(
            recipient_phone, {"type": "interactive", "interactive": interactive}
        )

    def mark_read(self, message_id: str) -> bool:
        """Best-effort read receipt. Never raises - a failed receipt must not
        affect message handling; returns True iff Meta accepted it."""
        url = f"{self._base}/{self._phone_number_id}/messages"
        body = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        try:
            self._request("POST", url, json=body)
            return True
        except MetaWhatsAppError:
            return False

    # --- media ------------------------------------------------------------

    def upload_media(self, data: bytes, *, filename: str, mime_type: str) -> str:
        """Upload bytes to Meta and return the resulting media id."""
        url = f"{self._base}/{self._phone_number_id}/media"
        files = {"file": (filename, data, mime_type)}
        payload = {"messaging_product": "whatsapp"}
        body = self._request("POST", url, files=files, data=payload)
        media_id = body.get("id")
        if not media_id:
            raise MetaWhatsAppInvalidResponse("meta media upload: missing media id")
        return str(media_id)

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Resolve a media id to its bytes + mime type (for inbound images)."""
        meta = self._request("GET", f"{self._base}/{media_id}")
        media_url = meta.get("url")
        if not media_url:
            raise MetaWhatsAppInvalidResponse("meta media: missing url")
        mime_type = str(meta.get("mime_type") or "application/octet-stream")
        try:
            response = self._client.get(str(media_url))
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise MetaWhatsAppTimeout("meta media download timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise self._map_status(exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise MetaWhatsAppUnavailable("meta media download failed") from exc
        return response.content, mime_type

    # --- internals --------------------------------------------------------

    def _send_message(self, recipient_phone: str, payload: dict[str, Any]) -> SendResult:
        if not recipient_phone:
            raise MetaWhatsAppInvalidRecipient("recipient phone is required")
        url = f"{self._base}/{self._phone_number_id}/messages"
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone,
            **payload,
        }
        data = self._request("POST", url, json=body)
        messages = data.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            provider_id = str(messages[0].get("id") or "")
            if provider_id:
                return SendResult(provider_message_id=provider_id, accepted=True)
        raise MetaWhatsAppInvalidResponse("meta send: missing message id in response")

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform a Graph API call with bounded retry on transient failures.

        A retry only follows a *transient* status (429/5xx/408) or a network/
        timeout error - a definitive 4xx (bad recipient, auth) is not retried.
        Error messages are fixed and never carry the auth header/token.
        """
        last_error: MetaWhatsAppError = MetaWhatsAppUnavailable("meta request failed")
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.request(method, url, json=json, data=data, files=files)
            except httpx.TimeoutException:
                last_error = MetaWhatsAppTimeout("meta request timed out")
            except httpx.HTTPError:
                # Connect/transport failure - retryable (request likely never landed).
                last_error = MetaWhatsAppUnavailable("meta request failed")
            else:
                if response.status_code < 400:
                    return self._parse_json(response)
                error = self._map_status(response.status_code)
                if response.status_code not in _RETRY_STATUS:
                    raise error  # definitive client error - do not retry
                last_error = error
            if attempt < self._max_retries:
                self._sleep(self._backoff_base * attempt)  # linear backoff
        raise last_error

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaWhatsAppInvalidResponse("meta returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise MetaWhatsAppInvalidResponse("meta returned an unexpected response shape")
        return payload

    @staticmethod
    def _map_status(status: int) -> MetaWhatsAppError:
        if status == 429:
            return MetaWhatsAppRateLimited("meta rate limit exceeded")
        if status in (401, 403):
            # Do NOT echo the response (may reflect the token) - use a fixed message.
            return MetaWhatsAppConfigError("meta authentication failed")
        if status == 400:
            return MetaWhatsAppInvalidRecipient("meta rejected the request (400)")
        return MetaWhatsAppUnavailable(f"meta returned {status}")
