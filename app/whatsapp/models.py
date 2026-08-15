"""Webhook idempotency table.

Meta delivers webhook events *at least once*: the same message can arrive more
than once (retries, redeliveries). ``ProcessedWebhookEvent`` records the provider
message id the first time it is handled; a globally-unique constraint makes a
second delivery fail to claim it, so it is ignored instead of reprocessed. This
prevents duplicate inventory adjustments, orders, and duplicate replies.

Meta message ids (``wamid...``) are globally unique, so the uniqueness is on the
id alone; ``business_id`` is kept for observability only.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db_mixins import TimestampMixin
from app.db import Base


class ProcessedWebhookEvent(TimestampMixin, Base):
    __tablename__ = "processed_webhook_event"
    __table_args__ = (
        Index(
            "uq_processed_webhook_provider_message_id",
            "provider_message_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The provider's own message/event id (Meta ``wamid...``). Globally unique.
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # Resolved tenant, for observability. Nullable: an event may be recorded even
    # when no business matched (so a redelivery of an unmapped event is still
    # short-circuited). Not a FK, to avoid coupling dedup to tenant lifecycle.
    business_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Coarse event category (e.g. "text", "image", "status") for logging.
    event_type: Mapped[str | None] = mapped_column(String(20), nullable=True)


class WhatsAppSession(TimestampMixin, Base):
    """Per-(business, customer phone) conversation state for the WhatsApp channel.

    Holds the current UX ``state`` (e.g. awaiting a search term) plus a small
    JSON ``data`` scratchpad for in-flight interaction context. It carries NO
    business facts - the authoritative data always lives in the domain services;
    this is only conversational bookkeeping so multi-step flows can resume.
    """

    __tablename__ = "whatsapp_session"
    __table_args__ = (Index("uq_wa_session_business_phone", "business_id", "phone", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="MENU")
    # Free-form interaction scratchpad (never authoritative). Null == empty.
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class WhatsAppStaff(TimestampMixin, Base):
    """Trusted mapping of a WhatsApp phone to seller/staff of a business.

    Populated only by server-side configuration/onboarding (never by a message).
    A sender whose phone appears here for the resolved business gets the seller
    UX; everyone else is a customer. Optionally links to an RBAC ``users`` row so
    seller identity ties back to the existing authorization model.
    """

    __tablename__ = "whatsapp_staff"
    __table_args__ = (Index("uq_wa_staff_business_phone", "business_id", "phone", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("business.id", ondelete="CASCADE"), nullable=False
    )
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
