"""Meta WhatsApp webhook - the public inbound channel.

Two endpoints under ``/webhooks/whatsapp``:

- ``GET``  : Meta's subscription handshake. Echoes ``hub.challenge`` only when
  ``hub.verify_token`` matches the configured token; otherwise 403.
- ``POST`` : inbound events. Verifies the ``X-Hub-Signature-256`` app-secret
  signature (when configured), normalizes the payload, and runs each message
  through the idempotent webhook service. Always returns 200 for authentic,
  well-formed deliveries so Meta does not retry/disable the subscription; a bad
  signature is 403 and a malformed body is a safe 200/ignore.

No authentication dependency is attached (Meta cannot present a JWT); trust comes
from the verify token and the request signature. No stack traces, ids, or secrets
are ever returned.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.config import Settings, get_settings
from app.whatsapp.dependencies import get_webhook_service
from app.whatsapp.parser import MetaWhatsAppParser
from app.whatsapp.service import WhatsAppWebhookService
from app.whatsapp.signature import verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


@router.get("")
def verify_webhook(
    request: Request, settings: Settings = Depends(get_settings)
) -> PlainTextResponse:
    """Meta webhook verification handshake."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token and token == settings.wa_verify_token:
        # Meta expects the raw challenge string echoed back with 200.
        return PlainTextResponse(challenge or "")
    logger.warning("whatsapp webhook verification failed (mode=%s)", mode)
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("")
async def receive_webhook(
    request: Request,
    service: WhatsAppWebhookService = Depends(get_webhook_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Ingest an inbound Meta webhook delivery."""
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(settings.wa_app_secret, raw, signature):
        logger.warning("whatsapp webhook: invalid signature")
        raise HTTPException(status_code=403, detail="invalid signature")

    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        # Malformed JSON is not retryable; acknowledge without processing.
        logger.warning("whatsapp webhook: malformed JSON body ignored")
        return {"status": "ignored"}

    started = time.perf_counter()
    messages = MetaWhatsAppParser.parse(payload)
    result = service.process(messages)
    duration_ms = (time.perf_counter() - started) * 1000.0
    logger.info(
        "whatsapp webhook handled: received=%d processed=%d duplicates=%d ignored=%d in %.0fms",
        len(messages),
        result.processed,
        result.duplicates,
        result.ignored,
        duration_ms,
    )
    return {
        "status": "ok",
        "received": len(messages),
        "processed": result.processed,
        "duplicates": result.duplicates,
        "ignored": result.ignored,
    }
