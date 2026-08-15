"""WhatsApp webhook orchestration + interaction router.

Resolves tenant + role + session, dedupes, then dispatches each inbound message
to a flow handler. It holds NO business logic - product/catalogue/order/payment/
invoice work lives in the domain services, reached through :class:`SellerFlow`
(seller catalogue) and :class:`ShopFlow` (customer commerce). Free-form natural
language still goes to the existing :class:`ConversationService`.

Invariants: tenant from Meta ``phone_number_id`` -> Business; role from the trusted
``whatsapp_staff`` mapping; idempotent per message id; catalogue-first; and the
webhook always returns 200 (every handler failure is contained).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.business.repository import BusinessRepository
from app.common.messaging import IncomingMessage, MessageType
from app.conversation import responses
from app.conversation.language import resolve_response_language
from app.conversation.service import ConversationService
from app.customer.service import CustomerService
from app.whatsapp import interactions, menus, seller_flow, shop_flow
from app.whatsapp.channel import WhatsAppChannel
from app.whatsapp.context import Ctx
from app.whatsapp.parser import ParsedWhatsAppMessage
from app.whatsapp.repository import (
    WebhookEventRepository,
    WhatsAppSessionRepository,
    WhatsAppStaffRepository,
)
from app.whatsapp.responder import WhatsAppResponder
from app.whatsapp.roles import WhatsAppRole, resolve_role
from app.whatsapp.seller_flow import SellerFlow
from app.whatsapp.shop_flow import ShopFlow

logger = logging.getLogger(__name__)

STATE_MENU = "MENU"
STATE_AWAITING_SEARCH = "AWAITING_SEARCH"
STATE_AWAITING_STOCK = "AWAITING_STOCK"

_GREETINGS = frozenset({"hi", "hello", "hey", "menu", "start", "help", "hola", "namaste"})


@dataclass
class WebhookProcessResult:
    processed: int = 0
    duplicates: int = 0
    ignored: int = 0
    replies: list[str] = field(default_factory=list)


class WhatsAppWebhookService:
    def __init__(
        self,
        session: Session,
        businesses: BusinessRepository,
        events: WebhookEventRepository,
        sessions: WhatsAppSessionRepository,
        staff: WhatsAppStaffRepository,
        customers: CustomerService,
        conversation: ConversationService,
        channel: WhatsAppChannel,
        seller: SellerFlow,
        shop: ShopFlow,
    ) -> None:
        self._session = session
        self._businesses = businesses
        self._events = events
        self._sessions = sessions
        self._staff = staff
        self._customers = customers
        self._conversation = conversation
        self._channel = channel
        self._seller = seller
        self._shop = shop

    # --- entry ------------------------------------------------------------

    def process(self, messages: list[ParsedWhatsAppMessage]) -> WebhookProcessResult:
        result = WebhookProcessResult()
        for message in messages:
            self._process_one(message, result)
        return result

    def _process_one(self, message: ParsedWhatsAppMessage, result: WebhookProcessResult) -> None:
        business = self._businesses.get_by_phone_number_id(message.phone_number_id)
        if business is None:
            logger.warning(
                "whatsapp webhook: no business for phone_number_id=%s (ignored)",
                message.phone_number_id,
            )
            result.ignored += 1
            return

        if not self._events.try_claim(
            message.message_id, business_id=business.id, event_type=message.raw_type
        ):
            logger.info("whatsapp webhook: duplicate message_id ignored (business=%s)", business.id)
            result.duplicates += 1
            return

        responder = WhatsAppResponder(self._channel, business.id, message.sender_phone)
        responder.mark_read(message.message_id)
        self._customers.get_or_create_by_phone(
            business.id, message.sender_phone, name=message.profile_name
        )
        role = resolve_role(self._staff, business.id, message.sender_phone)
        session = self._sessions.get_or_create(business.id, message.sender_phone)
        ctx = Ctx(business.id, message.sender_phone, role, session, responder, self._channel)

        # Contain every failure (Meta send error, AI outage, domain error): log,
        # attempt a safe fallback reply, and always keep the webhook at 200.
        try:
            self._dispatch(ctx, message)
        except Exception:
            logger.exception("whatsapp: message handling failed")
            responder.text("Sorry, something went wrong handling that. Please try again.")
        result.processed += 1
        try:
            self._session.commit()
        except Exception:
            logger.exception("whatsapp: commit failed")
            self._session.rollback()

    def _dispatch(self, ctx: Ctx, message: ParsedWhatsAppMessage) -> None:
        if message.message_type is MessageType.INTERACTIVE and message.interactive_id:
            self._route_interaction(ctx, message.interactive_id)
        elif message.message_type is MessageType.TEXT and message.text:
            self._route_text(ctx, message.text)
        elif message.message_type is MessageType.IMAGE:
            self._route_media(ctx, message)
        else:
            ctx.responder.text(responses.unsupported(resolve_response_language("")))

    # --- interaction routing (deterministic ids -> domain actions) -------

    def _route_interaction(self, ctx: Ctx, interaction_id: str) -> None:
        action, arg = interactions.parse(interaction_id)
        if action == interactions.NAV:
            self._show_menu(ctx)
        elif action == interactions.MENU:
            self._route_menu(ctx, arg)
        elif action == interactions.PRODUCT:
            self._shop.show_product(ctx, interactions.parse_product_id(arg))
        elif action == interactions.BUY:
            self._shop.buy_now(ctx, interactions.parse_product_id(arg))
        elif action == interactions.CART:
            self._shop.cart_op(ctx, arg)
        elif action == interactions.CHECKOUT:
            self._shop.checkout(ctx)
        elif action == interactions.ADDR:
            self._shop.use_address(ctx, arg)
        elif action == interactions.PAY_VERIFY:
            self._shop.verify_payment(ctx, arg)
        elif action == interactions.ORDER:
            self._shop.show_order(ctx, arg)
        elif action in (interactions.PUBLISH, interactions.EDIT_PRICE, interactions.CANCEL_DRAFT):
            self._route_seller_draft(ctx, action, interactions.parse_product_id(arg))
        else:
            logger.info("whatsapp: unknown interaction id ignored")
            self._show_menu(ctx)

    def _route_menu(self, ctx: Ctx, name: str | None) -> None:
        if name == "browse":
            self._shop.browse(ctx)
        elif name == "catalogue" and ctx.role is WhatsAppRole.STAFF:
            self._shop.browse(ctx, title="Your catalogue")
        elif name == "search":
            self._set_state(ctx, STATE_AWAITING_SEARCH)
            ctx.responder.text("🔎 What product are you looking for? Type a name.")
        elif name == "stock":
            self._set_state(ctx, STATE_AWAITING_STOCK)
            ctx.responder.text("📦 Which product's stock? Type its name.")
        elif name == "orders":
            self._shop.list_orders(ctx)
        elif name == "add_product" and ctx.role is WhatsAppRole.STAFF:
            self._seller.prompt_photo(ctx)
        else:
            self._show_menu(ctx)

    def _route_seller_draft(self, ctx: Ctx, action: str, draft_id: int | None) -> None:
        if ctx.role is not WhatsAppRole.STAFF or draft_id is None:
            self._show_menu(ctx)
            return
        if action == interactions.PUBLISH:
            self._seller.publish(ctx, draft_id)
        elif action == interactions.EDIT_PRICE:
            self._seller.edit_price(ctx, draft_id)
        else:
            self._seller.cancel(ctx, draft_id)

    # --- text routing -----------------------------------------------------

    def _route_text(self, ctx: Ctx, text: str) -> None:
        state = ctx.session.state
        low = text.strip().lower()

        if state == STATE_AWAITING_SEARCH:
            self._set_state(ctx, STATE_MENU)
            self._shop.search(ctx, text)
        elif state == STATE_AWAITING_STOCK:
            self._set_state(ctx, STATE_MENU)
            self._shop.stock(ctx, text)
        elif state == seller_flow.STATE_AWAITING_PRICE:
            self._seller.handle_price_reply(ctx, text)
        elif state == seller_flow.STATE_AWAITING_PHOTO:
            self._seller.reprompt_photo(ctx)
        elif state == shop_flow.STATE_AWAITING_ADDRESS:
            self._shop.address_reply(ctx, text)
        elif low in _GREETINGS:
            self._show_menu(ctx)
        else:
            self._free_form(ctx, text)

    def _free_form(self, ctx: Ctx, text: str) -> None:
        incoming = IncomingMessage(
            business_id=ctx.business_id,
            sender_phone=ctx.phone,
            message_id=f"wa-{ctx.phone}",
            message_type=MessageType.TEXT,
            text=text,
            timestamp=datetime.now(UTC),
            metadata={"channel": "whatsapp"},
        )
        self._conversation.handle(incoming)

    # --- media routing ----------------------------------------------------

    def _route_media(self, ctx: Ctx, message: ParsedWhatsAppMessage) -> None:
        if (
            ctx.role is WhatsAppRole.STAFF
            and message.message_type is MessageType.IMAGE
            and message.media is not None
        ):
            self._seller.handle_photo(ctx, message.media.media_id, message.text)
        else:
            ctx.responder.text(responses.unsupported(resolve_response_language("")))

    # --- helpers ----------------------------------------------------------

    def _show_menu(self, ctx: Ctx) -> None:
        self._set_state(ctx, STATE_MENU)
        ctx.responder.buttons(menus.main_menu(ctx.role))

    def _set_state(self, ctx: Ctx, state: str) -> None:
        ctx.session.state = state
