"""Read-only analytics DTOs (dataclasses; serialized by the API schemas)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SalesSummary:
    period: str
    order_count: int
    revenue: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class TopProduct:
    product_name: str
    units_sold: int
    revenue: Decimal


@dataclass(frozen=True, slots=True)
class LowStockItem:
    inventory_id: int
    product_id: int
    quantity: int
    low_stock_threshold: int


@dataclass(frozen=True, slots=True)
class PaymentTotals:
    period: str
    successful_count: int
    total: Decimal
    currency: str
