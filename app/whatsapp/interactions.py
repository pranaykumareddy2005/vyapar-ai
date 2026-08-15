"""Deterministic interaction-id scheme for WhatsApp buttons / list rows.

Every button and list row we send carries an id WE generate here (never free-form
user input). Meta echoes it back verbatim on tap, and the router dispatches on it.
Because the ids are server-generated and namespaced, routing is deterministic and
safe - a tapped id can only trigger the action we defined, never an arbitrary one.

Format: ``action`` or ``action:arg`` (single colon separator).
"""

from __future__ import annotations

_SEP = ":"

# --- actions ---------------------------------------------------------------
MENU = "menu"  # menu:<name>  (browse | search | stock | add_product | catalogue | orders)
NAV = "nav"  # nav:main
PRODUCT = "prod"  # prod:<product_id>  -> product detail card
BUY = "buy"  # buy:<product_id>   -> add to cart + go to checkout
# Cart (M15/M16): cart:<op>[:<product_id>]  op in add|inc|dec|rm|view|clear|checkout
CART = "cart"
# Seller draft review (M14): pub|editprice|cancel : <draft_id>
PUBLISH = "pub"  # pub:<draft_id>
EDIT_PRICE = "editprice"  # editprice:<draft_id>
CANCEL_DRAFT = "canceldraft"  # canceldraft:<draft_id>
# Checkout / payment (M16/M17)
CHECKOUT = "checkout"  # checkout  (uses current cart)
ADDR = "addr"  # addr:use:<address_id> | addr:new
PAY = "pay"  # pay:online:<order_id> | pay:cod:<order_id>
PAY_VERIFY = "payverify"  # payverify:<payment_id>
ORDER = "order"  # order:<order_id>  -> order status card


def build(action: str, arg: str | int | None = None) -> str:
    """Compose a namespaced interaction id."""
    return f"{action}{_SEP}{arg}" if arg is not None else action


def parse(interaction_id: str) -> tuple[str, str | None]:
    """Split an interaction id into ``(action, arg)``; arg is ``None`` if absent."""
    action, _, arg = interaction_id.partition(_SEP)
    return action, (arg or None)


def parse_product_id(arg: str | None) -> int | None:
    """Safely coerce a product-id argument to int (untrusted echo -> validated)."""
    if arg is None:
        return None
    try:
        value = int(arg)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
