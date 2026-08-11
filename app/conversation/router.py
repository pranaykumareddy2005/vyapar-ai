"""Conversation API - thin controller over ConversationService.

``business_id`` and ``actor_user_id`` come exclusively from the authenticated
principal; the AI can never influence them. Requires OWNER/EMPLOYEE (the pipeline
can mutate stock), consistent with the catalog/inventory mutation policy. This is
the vendor-neutral entry point - no WhatsApp/Meta webhook is exposed in Phase 6.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.auth.dependencies import Principal, require_role
from app.common.messaging import IncomingMessage, MessageType
from app.common.security import Role
from app.conversation.dependencies import get_conversation_service
from app.conversation.schemas import ConversationReply, ConversationRequest
from app.conversation.service import ConversationService

router = APIRouter(prefix="/api/conversation", tags=["conversation"])

_MUTATOR_ROLES = (Role.OWNER, Role.EMPLOYEE)


@router.post("/message", response_model=ConversationReply)
def handle_message(
    payload: ConversationRequest,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationReply:
    incoming = IncomingMessage(
        business_id=principal.business_id,  # tenant from the principal, never the AI
        sender_phone=payload.sender_phone,
        message_id=payload.message_id,
        message_type=MessageType.TEXT,
        text=payload.text,
        timestamp=datetime.now(UTC),
    )
    outcome = service.handle(incoming, actor_user_id=principal.user_id)
    return ConversationReply(
        reply=outcome.reply,
        intent=outcome.intent,
        outcome=outcome.outcome,
        provider_message_id=outcome.provider_message_id,
    )
