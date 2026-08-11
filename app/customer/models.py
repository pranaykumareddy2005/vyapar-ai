"""Customer + Address ORM models.

Both tenant-scoped by ``business_id``. Customer uses soft deletion (``is_deleted``)
so orders that reference a customer stay valid after the merchant removes them;
phone is unique per business among active customers only.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db_mixins import TimestampMixin
from app.db import Base


class Customer(TimestampMixin, Base):
    __tablename__ = "customer"
    __table_args__ = (
        # Phone unique per business among active customers; a soft-deleted
        # customer's phone can be reused (documented Phase-7 decision).
        Index(
            "uq_customer_business_phone_active",
            "business_id",
            "phone",
            unique=True,
            postgresql_where="is_deleted = false",
        ),
        Index("ix_customer_business_id", "business_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    addresses: Mapped[list[CustomerAddress]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="CustomerAddress.id",
    )


class CustomerAddress(TimestampMixin, Base):
    __tablename__ = "customer_address"
    __table_args__ = (Index("ix_customer_address_business_customer", "business_id", "customer_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("customer.id", ondelete="CASCADE"), nullable=False
    )
    line: Mapped[str] = mapped_column(String(300), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    pin: Mapped[str] = mapped_column(String(12), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="addresses")
