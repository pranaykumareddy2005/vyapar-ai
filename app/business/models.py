"""Business ORM model - the tenant/root entity.

Every merchant-owned record in the system is scoped to a ``business.id``.
The Business PIN hash lives here (nullable until the merchant sets it) and is
never exposed through any schema or log.
"""

from __future__ import annotations

import enum

from sqlalchemy import BigInteger, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db_mixins import TimestampMixin
from app.db import Base


class PaymentPreference(enum.StrEnum):
    """Merchant payment preference (FR-BUS-04)."""

    ONLINE = "ONLINE"
    COD = "COD"
    BOTH = "BOTH"


class Business(TimestampMixin, Base):
    __tablename__ = "business"
    __table_args__ = (
        # A WhatsApp number may be linked to at most one business (UC-01),
        # but only when set (partial unique index over non-null values).
        Index(
            "uq_business_whatsapp_number",
            "whatsapp_number",
            unique=True,
            postgresql_where="whatsapp_number IS NOT NULL",
        ),
        # A Meta WhatsApp phone-number-id maps to at most one business, so an
        # inbound webhook resolves its tenant deterministically (server-side
        # trust). Partial-unique over non-null values, mirroring the number index.
        Index(
            "uq_business_wa_phone_number_id",
            "whatsapp_phone_number_id",
            unique=True,
            postgresql_where="whatsapp_phone_number_id IS NOT NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_number: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)

    # Linked in a later onboarding step (FR-BUS-02); unique only when set.
    whatsapp_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Meta WhatsApp Cloud API "phone_number_id" (the numeric asset id of the
    # business's WhatsApp line, distinct from the E.164 number above). Set when
    # the merchant connects WhatsApp; the webhook uses it to resolve the tenant.
    whatsapp_phone_number_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Business PIN (FR-AUTH-03) - bcrypt hash, set after onboarding. Never
    # serialized or logged.
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    payment_preference: Mapped[PaymentPreference] = mapped_column(
        SAEnum(PaymentPreference, native_enum=False, length=20),
        nullable=False,
        default=PaymentPreference.COD,
        server_default=PaymentPreference.COD.value,
    )

    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
