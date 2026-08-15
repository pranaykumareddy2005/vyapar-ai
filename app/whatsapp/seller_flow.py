"""Seller catalogue flow over WhatsApp (M14).

Photo (+ price) → existing CatalogAI vision draft → seller review card
(Publish / Edit price / Cancel) → **CatalogService** creates the real product via
``CatalogAiService.approve``. The AI only drafts; the product is created solely by
the approval path, price is merchant-supplied, and the approver is a real RBAC
user (staff mapping or the business owner) - never invented.
"""

from __future__ import annotations

import contextlib
import logging

from app.auth.repository import UserRepository
from app.catalog.models import Product
from app.catalogai.provider import AiGenerationError
from app.catalogai.schemas import DraftEdit
from app.catalogai.service import CatalogAiService
from app.common.exceptions import ConflictError, DomainError, ValidationError
from app.common.security import Role
from app.whatsapp import menus
from app.whatsapp.context import Ctx
from app.whatsapp.parsing import parse_price
from app.whatsapp.repository import WhatsAppStaffRepository

logger = logging.getLogger(__name__)

# Session states owned by this flow.
STATE_AWAITING_PHOTO = "SELLER_AWAITING_PHOTO"
STATE_AWAITING_PRICE = "SELLER_AWAITING_PRICE"
STATE_REVIEW = "SELLER_REVIEW"

_KEY_DRAFT = "draft_id"


class SellerFlow:
    def __init__(
        self,
        catalog_ai: CatalogAiService,
        users: UserRepository,
        staff: WhatsAppStaffRepository,
    ) -> None:
        self._catalog_ai = catalog_ai
        self._users = users
        self._staff = staff

    # --- entry points -----------------------------------------------------

    def prompt_photo(self, ctx: Ctx) -> None:
        ctx.set_state(STATE_AWAITING_PHOTO)
        ctx.responder.text("📷 Send a photo of your product (put the price in the caption).")

    def handle_photo(self, ctx: Ctx, media_id: str, caption: str | None) -> None:
        """Download the photo, draft it with AI, and show the review card."""
        try:
            image, mime = ctx.channel.download_media(media_id)
        except Exception:
            logger.exception("seller photo: media download failed")
            ctx.responder.text("Sorry, I couldn't fetch that image. Please send it again.")
            return
        try:
            draft = self._catalog_ai.generate_draft(ctx.business_id, image=image, content_type=mime)
        except AiGenerationError:
            ctx.set_state(STATE_AWAITING_PHOTO)
            ctx.responder.text("I couldn't read that product photo. Please try a clearer image.")
            return

        ctx.put(_KEY_DRAFT, draft.id)
        price = parse_price(caption)
        if price is not None:
            self._catalog_ai.edit_draft(ctx.business_id, draft.id, DraftEdit(price=price))
            self._show_review(ctx, draft.id)
        else:
            ctx.set_state(STATE_AWAITING_PRICE)
            ctx.responder.text(
                f"📝 Draft ready: *{draft.name or 'your product'}*. "
                "Reply with the price (e.g. 150) to review and publish."
            )

    def handle_price_reply(self, ctx: Ctx, text: str) -> None:
        draft_id = self._draft_id(ctx)
        if draft_id is None:
            self.prompt_photo(ctx)
            return
        price = parse_price(text)
        if price is None:
            ctx.responder.text("Please reply with just the price, e.g. 150.")
            return
        try:
            self._catalog_ai.edit_draft(ctx.business_id, draft_id, DraftEdit(price=price))
        except DomainError:
            ctx.responder.text("That draft is no longer editable. Send a new photo to start over.")
            ctx.set_state("MENU")
            return
        self._show_review(ctx, draft_id)

    def edit_price(self, ctx: Ctx, draft_id: int) -> None:
        ctx.put(_KEY_DRAFT, draft_id)
        ctx.set_state(STATE_AWAITING_PRICE)
        ctx.responder.text("Reply with the new price (e.g. 150).")

    def publish(self, ctx: Ctx, draft_id: int) -> None:
        approver = self._approver_user_id(ctx)
        if approver is None:
            ctx.responder.text("Couldn't verify a seller account for publishing. Contact support.")
            return
        try:
            product = self._approve(ctx.business_id, draft_id, approver)
        except ValidationError as exc:
            ctx.responder.text(f"Can't publish yet: {exc.message}")
            return
        except ConflictError:
            ctx.responder.text("This draft can't be published (already handled).")
            return
        ctx.pop(_KEY_DRAFT)
        ctx.set_state("MENU")
        ctx.responder.text(
            f"🎉 Published! *{product.name}* is now live in your catalogue "
            f"(SKU {product.sku}, ₹{product.price_amt}, #{product.id})."
        )

    def cancel(self, ctx: Ctx, draft_id: int) -> None:
        with contextlib.suppress(DomainError):
            self._catalog_ai.reject(ctx.business_id, draft_id)
        ctx.pop(_KEY_DRAFT)
        ctx.set_state("MENU")
        ctx.responder.text("❌ Draft cancelled. Send another photo whenever you're ready.")

    def reprompt_photo(self, ctx: Ctx) -> None:
        ctx.responder.text("Please send a *photo* of the product, or type 'menu'.")

    # --- helpers ----------------------------------------------------------

    def _approve(self, business_id: int, draft_id: int, approver: int) -> Product:
        try:
            return self._catalog_ai.approve(business_id, draft_id, approver_user_id=approver)
        except ConflictError:
            # Most likely a duplicate SKU. Make it unique from the draft id and retry.
            draft = self._catalog_ai.get_draft(business_id, draft_id)
            base = (draft.sku_suggestion or "WA").strip() or "WA"
            self._catalog_ai.edit_draft(
                business_id, draft_id, DraftEdit(sku=f"{base}-{draft_id}"[:64])
            )
            return self._catalog_ai.approve(business_id, draft_id, approver_user_id=approver)

    def _show_review(self, ctx: Ctx, draft_id: int) -> None:
        draft = self._catalog_ai.get_draft(ctx.business_id, draft_id)
        details = draft.description or "No description."
        if draft.category_suggestion:
            details += f"\nCategory: {draft.category_suggestion}"
        price_line = (
            f"Price: ₹{draft.price_amt}" if draft.price_amt is not None else "Price: (set it)"
        )
        ctx.set_state(STATE_REVIEW)
        ctx.responder.buttons(
            menus.draft_review_card(
                draft_id=draft_id,
                name=draft.name or "Product",
                price_line=price_line,
                details=details[:600],
            )
        )

    def _draft_id(self, ctx: Ctx) -> int | None:
        value = ctx.get(_KEY_DRAFT)
        return int(value) if isinstance(value, int) else None

    def _approver_user_id(self, ctx: Ctx) -> int | None:
        staff = self._staff.get_staff(ctx.business_id, ctx.phone)
        if staff is not None and staff.user_id is not None:
            return staff.user_id
        users = self._users.list_by_business(ctx.business_id)
        for user in users:
            if user.role is Role.OWNER and user.is_active:
                return user.id
        for user in users:
            if user.is_active:
                return user.id
        return None
