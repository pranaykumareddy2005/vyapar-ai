"""Reusable ORM column mixins shared across domain models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds server-managed ``created_at`` / ``updated_at`` columns.

    Timestamps satisfy the audit requirement (NFR-SEC-02) at row level; a
    dedicated audit-log table is deferred to a later phase.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
