"""AI catalog draft ORM model + lifecycle enum.

The draft is kept strictly separate from the final ``Product`` (no incomplete
Product is ever used as a draft). It is tenant-scoped by ``business_id`` and holds
the AI-generated fields, provider provenance, an optional failure record, and
approval metadata. A merchant-supplied ``price_amt`` is the only source of price.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db_mixins import TimestampMixin
from app.db import Base


class DraftStatus(enum.StrEnum):
    """AI draft lifecycle (see docs/phase4_schema_decision.md §4)."""

    PENDING = "PENDING"  # row persisted, AI call in flight
    GENERATED = "GENERATED"  # AI succeeded; awaiting merchant review/edit/approval
    FAILED = "FAILED"  # provider failure / invalid output; retryable
    APPROVED = "APPROVED"  # merchant approved; Product created (terminal)
    REJECTED = "REJECTED"  # merchant discarded the draft (terminal)


# Only a GENERATED (reviewed) draft may be approved into a Product.
APPROVABLE_FROM: frozenset[DraftStatus] = frozenset({DraftStatus.GENERATED})
# A draft may be re-generated from these states (retry / re-draft).
REGENERATABLE_FROM: frozenset[DraftStatus] = frozenset(
    {DraftStatus.GENERATED, DraftStatus.FAILED, DraftStatus.PENDING}
)
# Terminal states never change again.
TERMINAL: frozenset[DraftStatus] = frozenset({DraftStatus.APPROVED, DraftStatus.REJECTED})


class CatalogAiDraft(TimestampMixin, Base):
    __tablename__ = "catalog_ai_draft"
    __table_args__ = (
        Index("ix_catalog_ai_draft_business_id", "business_id"),
        Index("ix_catalog_ai_draft_business_status", "business_id", "status"),
        # Optional idempotency key: unique per business only when supplied.
        Index(
            "uq_catalog_ai_draft_request_key",
            "business_id",
            "request_key",
            unique=True,
            postgresql_where="request_key IS NOT NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DraftStatus] = mapped_column(
        SAEnum(DraftStatus, native_enum=False, length=20), nullable=False
    )

    # Source image lives in object storage; only the reference is stored here.
    source_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # AI-generated, merchant-editable fields.
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_suggestion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("category.id", ondelete="SET NULL"), nullable=True
    )
    sku_suggestion: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Merchant-supplied ONLY - never inferred from the image.
    price_amt: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Provenance and failure record.
    ai_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    request_key: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Approval metadata (set only on the GENERATED -> APPROVED transition).
    approved_product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("product.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
