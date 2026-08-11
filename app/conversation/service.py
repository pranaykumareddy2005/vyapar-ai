"""ConversationService - orchestrates the intent pipeline.

IncomingMessage -> resolve intent -> confidence gate -> route to handler ->
domain service -> deterministic reply -> OutgoingMessage -> MessagingProvider.

The AI is data, not authority: ``business_id`` comes from the caller context
(never the model), and every provider/domain failure becomes a controlled
user-facing reply - stack traces, SQL, and provider details are never exposed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.catalog.service import CatalogService
from app.common.exceptions import DomainError
from app.common.messaging import IncomingMessage, MessagingProvider, OutgoingMessage
from app.conversation import responses
from app.conversation.handlers import HandlerResult, Outcome, build_registry
from app.conversation.provider import ConversationAiError, ConversationAiProvider
from app.conversation.schemas import IntentType
from app.inventory.service import InventoryService

logger = logging.getLogger(__name__)

_ACTIONABLE = frozenset({IntentType.SEARCH_PRODUCT, IntentType.GET_STOCK, IntentType.ADJUST_STOCK})


@dataclass(frozen=True, slots=True)
class ConversationOutcome:
    reply: str
    outcome: str
    intent: str | None
    provider_message_id: str


class ConversationService:
    def __init__(
        self,
        provider: ConversationAiProvider,
        messaging: MessagingProvider,
        catalog: CatalogService,
        inventory: InventoryService,
        *,
        confidence_threshold: float,
    ) -> None:
        self._provider = provider
        self._messaging = messaging
        self._registry = build_registry(catalog, inventory)
        self._threshold = confidence_threshold

    def handle(
        self, incoming: IncomingMessage, *, actor_user_id: int | None = None
    ) -> ConversationOutcome:
        text = (incoming.text or "").strip()
        if not text:
            return self._finish(
                incoming, HandlerResult(responses.empty_message(), Outcome.CLARIFICATION), None
            )

        try:
            resolved = self._provider.resolve(text)
        except ConversationAiError as exc:
            logger.warning("conversation AI provider failed: %s", exc.code)
            return self._finish(incoming, HandlerResult(responses.ai_error(), Outcome.ERROR), None)

        # Low-confidence actionable intents never execute (plan item 11).
        if resolved.intent in _ACTIONABLE and resolved.confidence < self._threshold:
            return self._finish(
                incoming,
                HandlerResult(responses.low_confidence(), Outcome.CLARIFICATION),
                resolved.intent,
            )

        handler = self._registry[resolved.intent]
        try:
            result = handler.handle(incoming.business_id, resolved, actor_user_id=actor_user_id)
        except DomainError as exc:
            # Backstop: handlers catch their expected domain errors; anything else
            # becomes a generic controlled reply (never leaks internals).
            logger.info("conversation domain error: %s", exc.code)
            result = HandlerResult(responses.internal_error(), Outcome.ERROR)
        except Exception:
            logger.exception("conversation handler crashed")
            result = HandlerResult(responses.internal_error(), Outcome.ERROR)

        return self._finish(incoming, result, resolved.intent)

    def _finish(
        self,
        incoming: IncomingMessage,
        result: HandlerResult,
        intent: IntentType | None,
    ) -> ConversationOutcome:
        outgoing = OutgoingMessage(
            business_id=incoming.business_id,
            recipient_phone=incoming.sender_phone,
            text=result.reply,
        )
        send = self._messaging.send(outgoing)
        return ConversationOutcome(
            reply=result.reply,
            outcome=result.outcome.value,
            intent=intent.value if intent is not None else None,
            provider_message_id=send.provider_message_id,
        )
