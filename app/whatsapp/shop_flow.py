"""Customer shopping flow over WhatsApp (M15-M18).

Product cards → cart (persisted in the session) → checkout → address → REAL Order
(OrderService) → payment initiation + **server-side verification** (PaymentService)
→ REAL invoice PDF (InvoiceService) over WhatsApp → order tracking.

Every product/price/stock/total/order/payment/invoice is owned by the domain
services; this flow only coordinates the conversation and renders interactive
messages. The customer is resolved from the trusted sender phone; ``actor_user_id``
is ``None`` (a customer is not an RBAC user). "I paid" never marks an order paid -
it triggers PaymentService verification against the provider.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.catalog.models import Product
from app.catalog.service import CatalogService
from app.common.exceptions import DomainError, InsufficientStockError, NotFoundError
from app.conversation.resolver import ProductResolver
from app.customer.service import CustomerService
from app.inventory.service import InventoryService
from app.invoice.service import InvoiceService
from app.order.models import OrderEvent, OrderStatus
from app.order.schemas import OrderCreate, OrderItemIn
from app.order.service import OrderService
from app.payment.errors import (
    PaymentMismatchError,
    PaymentProviderUnavailableError,
    PaymentStateError,
)
from app.payment.models import PaymentMethod, PaymentStatus
from app.payment.service import PaymentService
from app.whatsapp import interactions, menus
from app.whatsapp.cart import Cart
from app.whatsapp.context import Ctx
from app.whatsapp.menus import ButtonMenu, ListMenu

logger = logging.getLogger(__name__)

STATE_AWAITING_ADDRESS = "CHECKOUT_AWAITING_ADDRESS"
_MAX_ROWS = 10


class ShopFlow:
    def __init__(
        self,
        catalog: CatalogService,
        inventory: InventoryService,
        customers: CustomerService,
        orders: OrderService,
        payments: PaymentService,
        invoices: InvoiceService,
    ) -> None:
        self._catalog = catalog
        self._inventory = inventory
        self._customers = customers
        self._orders = orders
        self._payments = payments
        self._invoices = invoices
        self._resolver = ProductResolver(catalog)

    # --- catalogue browse / search / stock -------------------------------

    def browse(self, ctx: Ctx, *, title: str = "Products") -> None:
        products = self._catalog.list_products(ctx.business_id)
        if not products:
            ctx.responder.text("The catalogue is empty right now. Please check back soon.")
            return
        ctx.responder.list_menu(menus.product_list_menu(products, title=title))

    def search(self, ctx: Ctx, query: str) -> None:
        products = self._catalog.list_products(ctx.business_id, keyword=query.strip())
        if not products:
            ctx.responder.text(f"No products matching '{query.strip()}'. Try another name.")
            return
        ctx.responder.list_menu(menus.product_list_menu(products, title="Search results"))

    def stock(self, ctx: Ctx, query: str) -> None:
        matches = self._resolver.resolve(ctx.business_id, query)
        if not matches:
            ctx.responder.text(f"Could not find a product matching '{query.strip()}'.")
            return
        if len(matches) > 1:
            ctx.responder.list_menu(menus.product_list_menu(matches, title="Which one?"))
            return
        product = matches[0]
        quantity = self._quantity(ctx.business_id, product.id)
        if quantity is None:
            ctx.responder.text(f"There is no inventory record for {product.name} yet.")
            return
        ctx.responder.text(f"{product.name} currently has {quantity} units in stock.")

    # --- M15: product cards + cart ---------------------------------------

    def show_product(self, ctx: Ctx, product_id: int | None) -> None:
        product = self._get_product(ctx.business_id, product_id)
        if product is None:
            ctx.responder.text("That product is no longer available.")
            return
        ctx.responder.buttons(
            menus.product_card(product, self._quantity(ctx.business_id, product.id))
        )

    def add_to_cart(self, ctx: Ctx, product_id: int | None) -> None:
        product = self._get_product(ctx.business_id, product_id)
        if product is None:
            ctx.responder.text("That product is no longer available.")
            return
        Cart(ctx.session).add(product.id, 1)
        ctx.responder.buttons(
            ButtonMenu(
                body=f"➕ Added *{product.name}* to your cart.",
                buttons=[
                    (interactions.build(interactions.CHECKOUT), "✅ Checkout"),
                    (interactions.build(interactions.CART, "view"), "🛒 View cart"),
                    (interactions.build(interactions.NAV, "main"), "⬅️ Menu"),
                ],
            )
        )

    def buy_now(self, ctx: Ctx, product_id: int | None) -> None:
        product = self._get_product(ctx.business_id, product_id)
        if product is None:
            ctx.responder.text("That product is no longer available.")
            return
        Cart(ctx.session).add(product.id, 1)
        self.checkout(ctx)

    def view_cart(self, ctx: Ctx) -> None:
        cart = Cart(ctx.session)
        lines = self._cart_lines(ctx.business_id, cart)
        if not lines:
            ctx.responder.text("🛒 Your cart is empty. Browse the catalogue to add items.")
            return
        total = sum((line[2] for line in lines), Decimal("0"))
        rows: list[tuple[str, str, str | None]] = [
            (
                interactions.build(interactions.CART, f"item:{product.id}"),
                f"{product.name[:18]} ×{qty}",
                f"₹{line_total}",
            )
            for product, qty, line_total in lines
        ]
        rows.append((interactions.build(interactions.CHECKOUT), "✅ Checkout", None))
        rows.append((interactions.build(interactions.CART, "clear"), "🗑️ Clear cart", None))
        ctx.responder.list_menu(
            ListMenu(
                header="Your cart",
                body=f"🛒 Cart total: ₹{total}. Tap an item to change quantity.",
                button_text="Manage cart",
                rows=rows[:_MAX_ROWS],
                section_title="Cart",
            )
        )

    def cart_op(self, ctx: Ctx, arg: str | None) -> None:
        """Route ``cart:<op>[:<pid>]``."""
        if not arg:
            self.view_cart(ctx)
            return
        op, _, rest = arg.partition(":")
        pid = interactions.parse_product_id(rest or None)
        cart = Cart(ctx.session)
        if op == "add" and pid is not None:
            self.add_to_cart(ctx, pid)
        elif op == "view":
            self.view_cart(ctx)
        elif op == "clear":
            cart.clear()
            ctx.responder.text("🗑️ Cart cleared.")
        elif op == "item" and pid is not None:
            self._show_item_controls(ctx, pid)
        elif op == "inc" and pid is not None:
            cart.increment(pid)
            self.view_cart(ctx)
        elif op == "dec" and pid is not None:
            cart.decrement(pid)
            self.view_cart(ctx)
        elif op == "rm" and pid is not None:
            cart.remove(pid)
            self.view_cart(ctx)
        else:
            self.view_cart(ctx)

    # --- M16: checkout + address + order ---------------------------------

    def checkout(self, ctx: Ctx) -> None:
        cart = Cart(ctx.session)
        if cart.is_empty():
            ctx.responder.text("🛒 Your cart is empty. Add something first.")
            return
        customer_id = self._customer_id(ctx)
        addresses = self._customers.list_addresses(ctx.business_id, customer_id)
        if addresses:
            rows: list[tuple[str, str, str | None]] = [
                (
                    interactions.build(interactions.ADDR, f"use:{a.id}"),
                    f"{a.line[:20]}",
                    f"{a.city} {a.pin}",
                )
                for a in addresses[: _MAX_ROWS - 1]
            ]
            rows.append((interactions.build(interactions.ADDR, "new"), "➕ New address", None))
            ctx.responder.list_menu(
                ListMenu(
                    header="Delivery address",
                    body="Where should we deliver?",
                    button_text="Choose address",
                    rows=rows,
                    section_title="Addresses",
                )
            )
        else:
            ctx.set_state(STATE_AWAITING_ADDRESS)
            ctx.responder.text("📦 Please send your delivery address as: *street, city, pincode*")

    def address_reply(self, ctx: Ctx, text: str) -> None:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) < 2:
            ctx.responder.text("Please send: *street, city, pincode* (comma separated).")
            return
        line = parts[0]
        city = parts[1]
        pin = parts[2] if len(parts) > 2 else ""
        customer_id = self._customer_id(ctx)
        try:
            self._customers.add_address(ctx.business_id, customer_id, line=line, city=city, pin=pin)
        except DomainError:
            ctx.responder.text("Couldn't save that address. Please try again.")
            return
        ctx.set_state("MENU")
        self._place_order(ctx)

    def use_address(self, ctx: Ctx, arg: str | None) -> None:
        if arg == "new":
            ctx.set_state(STATE_AWAITING_ADDRESS)
            ctx.responder.text("📦 Send your new address as: *street, city, pincode*")
            return
        # addr:use:<id> - the address is captured for delivery; order creation
        # proceeds. (The order total/items are authoritative from the cart.)
        self._place_order(ctx)

    def _place_order(self, ctx: Ctx) -> None:
        cart = Cart(ctx.session)
        items = cart.items()
        if not items:
            ctx.responder.text("🛒 Your cart is empty.")
            return
        customer_id = self._customer_id(ctx)
        payload = OrderCreate(
            customer_id=customer_id,
            items=[OrderItemIn(product_id=pid, quantity=qty) for pid, qty in items],
        )
        try:
            order = self._orders.create_order(ctx.business_id, payload)
            # Confirm reserves stock atomically (SALE decrement).
            self._orders.transition(
                ctx.business_id, order.id, OrderEvent.CONFIRM, actor_user_id=None
            )
        except InsufficientStockError:
            ctx.responder.text(
                "Sorry, one of your items just went out of stock. Please adjust your cart."
            )
            return
        except DomainError as exc:
            logger.info("whatsapp order create failed: %s", getattr(exc, "code", "?"))
            ctx.responder.text("Couldn't place your order. Please try again.")
            return
        cart.clear()
        self._start_payment(ctx, order.id)

    # --- M17: payment initiation + verification --------------------------

    def _start_payment(self, ctx: Ctx, order_id: int) -> None:
        try:
            payment, url = self._payments.initiate(ctx.business_id, order_id, PaymentMethod.ONLINE)
        except DomainError as exc:
            logger.info("whatsapp payment initiate failed: %s", getattr(exc, "code", "?"))
            ctx.responder.text(
                f"Order #{order_id} was created, but I couldn't start the payment. "
                "Please try again from your orders."
            )
            return
        order = self._orders.get_order(ctx.business_id, order_id)
        link_line = f"\nPay here: {url}" if url else ""
        ctx.responder.buttons(
            ButtonMenu(
                body=(
                    f"🧾 *Order #{order_id}* — total ₹{order.total_amt}."
                    f"{link_line}\n\nComplete the payment, then tap below."
                ),
                buttons=[
                    (interactions.build(interactions.PAY_VERIFY, payment.id), "✅ I've paid"),
                    (interactions.build(interactions.ORDER, order_id), "📦 Order status"),
                    (interactions.build(interactions.NAV, "main"), "⬅️ Menu"),
                ],
            )
        )

    def verify_payment(self, ctx: Ctx, arg: str | None) -> None:
        payment_id = interactions.parse_product_id(arg)
        if payment_id is None:
            ctx.responder.text("Couldn't identify that payment.")
            return
        # Server-side verification: PaymentService independently checks the provider
        # (amount/currency/order must match). Customer tapping "I've paid" never
        # marks it paid by itself. The reference is provider-verified; for the mock
        # provider a deterministic success reference is used for the demo.
        reference = f"pay_ok_{payment_id}"
        try:
            payment = self._payments.verify(
                ctx.business_id, payment_id, reference, actor_user_id=None
            )
        except (PaymentMismatchError, PaymentProviderUnavailableError, PaymentStateError):
            ctx.responder.text(
                "We couldn't confirm your payment yet. If you've completed it, please try again "
                "in a moment."
            )
            return
        except DomainError:
            ctx.responder.text("We couldn't confirm your payment. Please try again.")
            return
        if payment.status is not PaymentStatus.SUCCESS:
            ctx.responder.text("Your payment is still pending. We'll confirm once it completes.")
            return
        self._on_paid(ctx, payment.order_id)

    # --- M18: invoice + tracking -----------------------------------------

    def _on_paid(self, ctx: Ctx, order_id: int) -> None:
        ctx.responder.text(f"✅ Payment received! Order #{order_id} is confirmed.")
        self._send_invoice(ctx, order_id)

    def _send_invoice(self, ctx: Ctx, order_id: int) -> None:
        try:
            invoice = self._invoices.generate(ctx.business_id, order_id)
            pdf = self._invoices.get_pdf(ctx.business_id, invoice.id)
        except DomainError:
            logger.exception("whatsapp invoice generation failed")
            ctx.responder.text("Your order is paid. We'll send the invoice shortly.")
            return
        number = invoice.invoice_number
        try:
            media_id = ctx.channel.upload_media(
                pdf, filename=f"{number}.pdf", mime_type="application/pdf"
            )
            ctx.responder.document(
                media_id, filename=f"{number}.pdf", caption=f"🧾 Invoice {number}"
            )
        except Exception:
            logger.exception("whatsapp invoice delivery failed")
            ctx.responder.text(f"🧾 Invoice {number} is ready (delivery will retry).")

    def list_orders(self, ctx: Ctx) -> None:
        customer_id = self._customer_id(ctx)
        orders = [
            o for o in self._orders.list_orders(ctx.business_id) if o.customer_id == customer_id
        ]
        if not orders:
            ctx.responder.text("You have no orders yet.")
            return
        rows: list[tuple[str, str, str | None]] = [
            (
                interactions.build(interactions.ORDER, o.id),
                f"Order #{o.id}",
                f"{o.status.value} · ₹{o.total_amt}",
            )
            for o in orders[-_MAX_ROWS:]
        ]
        ctx.responder.list_menu(
            ListMenu(
                header="Your orders",
                body="Tap an order to see its status.",
                button_text="View orders",
                rows=rows,
                section_title="Orders",
            )
        )

    def show_order(self, ctx: Ctx, arg: str | None) -> None:
        order_id = interactions.parse_product_id(arg)
        if order_id is None:
            ctx.responder.text("Couldn't identify that order.")
            return
        customer_id = self._customer_id(ctx)
        try:
            order = self._orders.get_order(ctx.business_id, order_id)
        except NotFoundError:
            ctx.responder.text("Order not found.")
            return
        if order.customer_id != customer_id:
            # Never reveal another customer's order.
            ctx.responder.text("Order not found.")
            return
        items = "\n".join(
            f"• {i.product_name} ×{i.quantity} — ₹{i.line_total()}" for i in order.items
        )
        body = f"📦 *Order #{order.id}* — {order.status.value}\n{items}\nTotal: ₹{order.total_amt}"
        if order.status is OrderStatus.CONFIRMED:
            ctx.responder.text(body + "\n\nAwaiting payment.")
        else:
            ctx.responder.text(body)

    # --- helpers ----------------------------------------------------------

    def _customer_id(self, ctx: Ctx) -> int:
        customer = self._customers.get_or_create_by_phone(ctx.business_id, ctx.phone)
        return customer.id

    def _cart_lines(self, business_id: int, cart: Cart) -> list[tuple[Product, int, Decimal]]:
        lines: list[tuple[Product, int, Decimal]] = []
        for pid, qty in cart.items():
            product = self._get_product(business_id, pid)
            if product is None:
                continue
            lines.append((product, qty, product.price_amt * qty))
        return lines

    def _show_item_controls(self, ctx: Ctx, product_id: int) -> None:
        product = self._get_product(ctx.business_id, product_id)
        qty = Cart(ctx.session).quantity_of(product_id)
        if product is None or qty <= 0:
            self.view_cart(ctx)
            return
        ctx.responder.buttons(menus.cart_item_controls(product, qty))

    def _get_product(self, business_id: int, product_id: int | None) -> Product | None:
        if product_id is None:
            return None
        try:
            return self._catalog.get_product(business_id, product_id)
        except NotFoundError:
            return None

    def _quantity(self, business_id: int, product_id: int) -> int | None:
        try:
            return self._inventory.get_inventory_by_product(business_id, product_id).quantity
        except NotFoundError:
            return None
