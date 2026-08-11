"""Invoice ORM models: Invoice, InvoiceItem, InvoiceCounter.

All tenant-scoped by ``business_id``. An order has at most one invoice (unique
``order_id``); invoice numbers are unique per business. Every value is an immutable
snapshot - no invoice field is edited after issuance. ``InvoiceCounter`` is the
atomic, gap-free per-business-per-year sequence source (LLD §7.4).
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db_mixins import TimestampMixin
from app.db import Base


class InvoiceStatus(enum.StrEnum):
    """Invoices are created ISSUED and are immutable thereafter (no edit/cancel)."""

    ISSUED = "ISSUED"


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoice"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_invoice_order"),
        UniqueConstraint("business_id", "invoice_number", name="uq_invoice_business_number"),
        CheckConstraint("total_amt >= 0", name="ck_invoice_total_non_negative"),
        Index("ix_invoice_business_id", "business_id"),
        Index("ix_invoice_business_status", "business_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        SAEnum(InvoiceStatus, native_enum=False, length=20), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Financial snapshot (from the authoritative Order at issuance).
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_amt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Customer / business snapshot.
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Payment snapshot (read from the successful Payment; never mutated here).
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False)

    # PDF document reference (populated after render/store; NULL until then).
    pdf_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceItem.id",
    )


class InvoiceItem(TimestampMixin, Base):
    __tablename__ = "invoice_item"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_invoice_item_quantity_positive"),
        Index("ix_invoice_item_business_invoice", "business_id", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("invoice.id", ondelete="CASCADE"), nullable=False
    )
    # Reference only; the snapshot fields below are authoritative for the invoice.
    product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("product.id", ondelete="SET NULL"), nullable=True
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class InvoiceCounter(Base):
    """Atomic per-business-per-year sequence for gap-free invoice numbers."""

    __tablename__ = "invoice_counter"

    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), primary_key=True
    )
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_seq: Mapped[int] = mapped_column(Integer, nullable=False)
