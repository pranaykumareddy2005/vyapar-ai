"""Deterministic response templates.

The LLM never invents the final business result; replies are built here from the
actual values returned by the domain services (plan items 15, 28).
"""

from __future__ import annotations

from app.catalog.models import Product

_MAX_LISTED = 5


def search_results(products: list[Product]) -> str:
    shown = products[:_MAX_LISTED]
    items = ", ".join(f"{p.name} (SKU {p.sku}, ₹{p.price_amt})" for p in shown)
    extra = "" if len(products) <= _MAX_LISTED else f" (+{len(products) - _MAX_LISTED} more)"
    return f"Found {len(products)} product(s): {items}{extra}."


def not_found(query: str) -> str:
    return f"Could not find a product matching '{query}'."


def multiple_matches(query: str, products: list[Product]) -> str:
    names = ", ".join(p.name for p in products[:_MAX_LISTED])
    return f"I found multiple products matching '{query}': {names}. Which one did you mean?"


def stock_level(product_name: str, quantity: int) -> str:
    return f"{product_name} currently has {quantity} units in stock."


def no_inventory(product_name: str) -> str:
    return f"There is no inventory record for {product_name} yet."


def adjusted(product_name: str, delta: int, quantity: int) -> str:
    if delta >= 0:
        return f"Added {delta} to {product_name}. Current stock: {quantity}."
    return f"Removed {abs(delta)} from {product_name}. Current stock: {quantity}."


def insufficient_stock(product_name: str, requested: int, current: int) -> str:
    return f"Not enough stock to remove {requested} from {product_name}. Current stock: {current}."


def missing_product() -> str:
    return "Which product would you like to adjust?"


def missing_quantity(product_query: str, increasing: bool) -> str:
    verb = "add" if increasing else "remove"
    return f"How many units of {product_query} would you like to {verb}?"


def missing_search_product() -> str:
    return "What product would you like to search for?"


def unsupported() -> str:
    return (
        "Sorry, I can only help with product search, stock checks, and inventory "
        "adjustments right now."
    )


def low_confidence() -> str:
    return "I'm not sure I understood. Could you rephrase, including the product and amount?"


def empty_message() -> str:
    return "Please send a text message describing what you need."


def ai_error() -> str:
    return "Sorry, I couldn't process that right now. Please try again."


def internal_error() -> str:
    return "Sorry, something went wrong handling that. Please try again."
