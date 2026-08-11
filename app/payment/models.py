"""Payment ORM model + state machine.

Tenant-scoped by ``business_id``. An order may have several payment attempts but at
most one ``SUCCESS`` (partial-unique index). Money is ``NUMERIC(12,2)``. The status
is a guarded state machine: SUCCESS/FAILED/CANCELLED are terminal; a late failure
callback can never flip SUCCESS→FAILED, and a retry after FAILED is a new row.
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
    Numeric,
    String,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db_mixins import TimestampMixin
from app.db import Base


class PaymentMethod(enum.StrEnum):
    ONLINE = "ONLINE"
    COD = "COD"


class PaymentStatus(enum.StrEnum):
    CREATED = "CREATED"  # initiated; awaiting verification/confirmation
    PENDING = "PENDING"  # provider reports in-progress
    SUCCESS = "SUCCESS"  # verified successful (terminal)
    FAILED = "FAILED"  # verification failed (terminal; retry = new attempt)
    CANCELLED = "CANCELLED"  # attempt abandoned (terminal)


# A payment may be verified/confirmed only from these non-terminal states.
VERIFIABLE_FROM: frozenset[PaymentStatus] = frozenset(
    {PaymentStatus.CREATED, PaymentStatus.PENDING}
)
TERMINAL: frozenset[PaymentStatus] = frozenset(
    {PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.CANCELLED}
)


class Payment(TimestampMixin, Base):
    __tablename__ = "payment"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        # At most one successful payment per order (LLD "owns exactly one Payment";
        # PDD "no partial payments").
        Index(
            "uq_payment_order_success",
            "order_id",
            unique=True,
            postgresql_where="status = 'SUCCESS'",
        ),
        # A provider payment id can back only one payment (blocks replay / dup callback).
        Index(
            "uq_payment_provider_payment_id",
            "business_id",
            "provider_payment_id",
            unique=True,
            postgresql_where="provider_payment_id IS NOT NULL",
        ),
        # Idempotent initiation.
        Index(
            "uq_payment_idempotency_key",
            "business_id",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        Index("ix_payment_business_id", "business_id"),
        Index("ix_payment_business_order", "business_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(PaymentMethod, native_enum=False, length=20), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, native_enum=False, length=20), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
