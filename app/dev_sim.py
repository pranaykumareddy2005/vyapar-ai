"""Development-only message simulation endpoints.

Let developers push a message through the messaging boundary without WhatsApp/Meta.

- ``/dev/simulate-message`` is a simple acknowledgement echo through the
  messaging boundary.
- ``/dev/simulate-conversation`` runs the full conversation pipeline
  (IncomingMessage -> ConversationService -> Mock AI -> handler -> domain service
  -> OutgoingMessage -> MockMessagingProvider), proving the pipeline without a
  Meta or Gemini key. ``business_id`` here simulates the channel resolving which
  business a message arrived for; the AI never controls it.

Both are mounted only outside production.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.common.messaging import (
    IncomingMessage,
    MessageType,
    MessagingProvider,
    OutgoingMessage,
)
from app.conversation.dependencies import get_conversation_service
from app.conversation.service import ConversationService
from app.providers import get_messaging_provider

router = APIRouter(prefix="/dev", tags=["dev"])


class SimulateMessageRequest(BaseModel):
    business_id: int = Field(gt=0)
    sender_phone: str = Field(min_length=3, max_length=20)
    text: str = Field(min_length=1, max_length=4096)
    message_id: str = Field(default="dev-msg", max_length=128)


class SimulateMessageResponse(BaseModel):
    normalized: dict[str, str | int | None]
    reply_text: str
    provider_message_id: str


@router.post("/simulate-message", response_model=SimulateMessageResponse)
def simulate_message(
    payload: SimulateMessageRequest,
    messaging: MessagingProvider = Depends(get_messaging_provider),
) -> SimulateMessageResponse:
    """Simulate an inbound message and reply through the provider."""
    incoming = IncomingMessage(
        business_id=payload.business_id,
        sender_phone=payload.sender_phone,
        message_id=payload.message_id,
        message_type=MessageType.TEXT,
        text=payload.text,
        timestamp=datetime.now(UTC),
    )

    # Simple acknowledgement echo. For the full intent pipeline use
    # /dev/simulate-conversation; the provider boundary below is identical.
    reply_text = f"Received: {incoming.text}"
    outgoing = OutgoingMessage(
        business_id=incoming.business_id,
        recipient_phone=incoming.sender_phone,
        text=reply_text,
    )
    result = messaging.send(outgoing)

    return SimulateMessageResponse(
        normalized={
            "business_id": incoming.business_id,
            "sender_phone": incoming.sender_phone,
            "message_id": incoming.message_id,
            "message_type": incoming.message_type.value,
            "text": incoming.text,
        },
        reply_text=reply_text,
        provider_message_id=result.provider_message_id,
    )


class SimulateConversationResponse(BaseModel):
    reply: str
    intent: str | None
    outcome: str
    provider_message_id: str


@router.post("/simulate-conversation", response_model=SimulateConversationResponse)
def simulate_conversation(
    payload: SimulateMessageRequest,
    conversation: ConversationService = Depends(get_conversation_service),
) -> SimulateConversationResponse:
    """Run the full conversation pipeline for a simulated inbound message."""
    incoming = IncomingMessage(
        business_id=payload.business_id,  # simulates channel-resolved tenant
        sender_phone=payload.sender_phone,
        message_id=payload.message_id,
        message_type=MessageType.TEXT,
        text=payload.text,
        timestamp=datetime.now(UTC),
    )
    outcome = conversation.handle(incoming)
    return SimulateConversationResponse(
        reply=outcome.reply,
        intent=outcome.intent,
        outcome=outcome.outcome,
        provider_message_id=outcome.provider_message_id,
    )
