"""Conversational shopping cart, persisted in the WhatsApp session.

The cart is *conversation state*, not a domain entity: it holds only chosen
``(product_id, quantity)`` pairs in ``session.data['cart']``. Prices, stock, and
the order total are NEVER stored here - they are always read from CatalogService /
InventoryService / OrderService at the moment they are needed, so the cart can
never drift from catalogue truth. Checkout turns the cart into a real Order via
OrderService.

Mutations reassign ``session.data`` (a JSON column) so SQLAlchemy flags it dirty.
"""

from __future__ import annotations

from typing import Any

from app.whatsapp.models import WhatsAppSession

_KEY = "cart"


class Cart:
    def __init__(self, session: WhatsAppSession) -> None:
        self._session = session

    def _rows(self) -> list[dict[str, int]]:
        data = self._session.data or {}
        rows = data.get(_KEY) or []
        return [dict(r) for r in rows if isinstance(r, dict)]

    def _save(self, rows: list[dict[str, int]]) -> None:
        data: dict[str, Any] = dict(self._session.data or {})
        data[_KEY] = [r for r in rows if r.get("qty", 0) > 0]
        self._session.data = data  # reassign so the JSON column is marked dirty

    def items(self) -> list[tuple[int, int]]:
        """Return ``[(product_id, quantity), ...]`` for positive quantities."""
        out: list[tuple[int, int]] = []
        for r in self._rows():
            try:
                pid, qty = int(r["product_id"]), int(r["qty"])
            except (KeyError, TypeError, ValueError):
                continue
            if qty > 0:
                out.append((pid, qty))
        return out

    def is_empty(self) -> bool:
        return not self.items()

    def total_quantity(self) -> int:
        return sum(qty for _, qty in self.items())

    def add(self, product_id: int, quantity: int = 1) -> None:
        rows = self._rows()
        for r in rows:
            if int(r.get("product_id", 0)) == product_id:
                r["qty"] = int(r.get("qty", 0)) + quantity
                self._save(rows)
                return
        rows.append({"product_id": product_id, "qty": quantity})
        self._save(rows)

    def set_quantity(self, product_id: int, quantity: int) -> None:
        rows = [r for r in self._rows() if int(r.get("product_id", 0)) != product_id]
        if quantity > 0:
            rows.append({"product_id": product_id, "qty": quantity})
        self._save(rows)

    def quantity_of(self, product_id: int) -> int:
        for pid, qty in self.items():
            if pid == product_id:
                return qty
        return 0

    def increment(self, product_id: int) -> None:
        self.add(product_id, 1)

    def decrement(self, product_id: int) -> None:
        self.set_quantity(product_id, max(0, self.quantity_of(product_id) - 1))

    def remove(self, product_id: int) -> None:
        self.set_quantity(product_id, 0)

    def clear(self) -> None:
        self._save([])
