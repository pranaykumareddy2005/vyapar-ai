"""Interactive message builders (pure, no I/O).

Produces :class:`ButtonMenu` / :class:`ListMenu` value objects from role and from
real catalogue data supplied by the caller. These builders hold NO business logic
and never fetch data themselves - the router passes in products/quantities it read
from ``CatalogService`` / ``InventoryService``. The ids embedded here come from
:mod:`app.whatsapp.interactions`, so taps route deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.catalog.models import Product
from app.whatsapp import interactions
from app.whatsapp.roles import WhatsAppRole

_MAX_ROWS = 10


@dataclass(frozen=True)
class ButtonMenu:
    body: str
    buttons: list[tuple[str, str]]  # (interaction_id, title<=20 chars)
    header: str | None = None


@dataclass(frozen=True)
class ListMenu:
    body: str
    button_text: str
    rows: list[tuple[str, str, str | None]]  # (interaction_id, title, description)
    header: str | None = None
    section_title: str = "Products"


def main_menu(role: WhatsAppRole) -> ButtonMenu:
    """The role-aware entry-point menu (max 3 reply buttons)."""
    if role is WhatsAppRole.STAFF:
        return ButtonMenu(
            header="Vyapar AI · Seller",
            body="What would you like to do?",
            buttons=[
                (interactions.build(interactions.MENU, "add_product"), "📷 Add product"),
                (interactions.build(interactions.MENU, "catalogue"), "📋 My catalogue"),
                (interactions.build(interactions.MENU, "stock"), "📦 Check stock"),
            ],
        )
    return ButtonMenu(
        header="Vyapar AI",
        body="Welcome! How can I help you shop today?",
        buttons=[
            (interactions.build(interactions.MENU, "browse"), "🛍️ Browse"),
            (interactions.build(interactions.MENU, "search"), "🔎 Search"),
            (interactions.build(interactions.MENU, "stock"), "📦 Check stock"),
        ],
    )


def _price(product: Product) -> str:
    return f"₹{product.price_amt}"


def product_list_menu(products: list[Product], *, title: str = "Products") -> ListMenu:
    """A tappable list of real catalogue products (rows carry ``prod:<id>``)."""
    rows: list[tuple[str, str, str | None]] = [
        (
            interactions.build(interactions.PRODUCT, product.id),
            product.name[:24],
            f"{_price(product)} · SKU {product.sku}",
        )
        for product in products[:_MAX_ROWS]
    ]
    extra = "" if len(products) <= _MAX_ROWS else f" (showing first {_MAX_ROWS})"
    return ListMenu(
        header="Catalogue",
        body=f"Found {len(products)} product(s){extra}. Tap one to see details.",
        button_text="View products",
        rows=rows,
        section_title=title[:24],
    )


def product_card(product: Product, quantity: int | None) -> ButtonMenu:
    """Detail card for one product with Buy + Add-to-cart (routes to order flow)."""
    stock_line = f"In stock: {quantity}" if quantity is not None else "Stock: not tracked yet"
    body = f"*{product.name}*\nPrice: {_price(product)}\nSKU: {product.sku}\n{stock_line}"
    return ButtonMenu(
        body=body,
        buttons=[
            (interactions.build(interactions.BUY, product.id), "🛒 Buy now"),
            (interactions.build(interactions.CART, f"add:{product.id}"), "➕ Add to cart"),
            (interactions.build(interactions.NAV, "main"), "⬅️ Menu"),
        ],
    )


def draft_review_card(*, draft_id: int, name: str, price_line: str, details: str) -> ButtonMenu:
    """Seller review card for an AI-generated catalogue draft."""
    body = f"📝 *Draft*\n{name}\n{details}\n{price_line}\n\nPublish to your catalogue?"
    return ButtonMenu(
        body=body,
        buttons=[
            (interactions.build(interactions.PUBLISH, draft_id), "✅ Publish"),
            (interactions.build(interactions.EDIT_PRICE, draft_id), "✏️ Edit price"),
            (interactions.build(interactions.CANCEL_DRAFT, draft_id), "❌ Cancel"),
        ],
    )


def cart_item_controls(product: Product, quantity: int) -> ButtonMenu:
    """Per-item quantity controls shown when a cart row is tapped."""
    body = f"*{product.name}* × {quantity}\nPrice: {_price(product)} each"
    return ButtonMenu(
        body=body,
        buttons=[
            (interactions.build(interactions.CART, f"inc:{product.id}"), "➕ Add one"),
            (interactions.build(interactions.CART, f"dec:{product.id}"), "➖ Remove one"),
            (interactions.build(interactions.CART, f"rm:{product.id}"), "🗑️ Remove item"),
        ],
    )
