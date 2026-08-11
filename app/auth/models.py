"""User ORM model - belongs to exactly one Business (tenant).

``business_id`` is the tenant key enforced by the repository layer on every
query. ``email`` is globally unique so login resolves a single user; a user is
deactivated via ``is_active`` (no hard delete in the MVP).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db_mixins import TimestampMixin
from app.common.security import Role
from app.db import Base


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_business_id", "business_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("business.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, native_enum=False, length=20),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
