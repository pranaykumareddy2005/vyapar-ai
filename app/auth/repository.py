"""Data access for users, with tenant isolation baked into every query.

Cross-tenant reads/writes are impossible through this repository: all
business-scoped methods require and filter by ``business_id``. The only
tenant-agnostic method is :meth:`get_by_email`, used pre-authentication during
login (before a tenant context exists).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> User:
        self._session.add(user)
        self._session.flush()
        return user

    def get_by_email(self, email: str) -> User | None:
        """Pre-auth lookup by globally-unique email (no tenant filter)."""
        stmt = select(User).where(User.email == email)
        return self._session.scalars(stmt).one_or_none()

    def email_exists(self, email: str) -> bool:
        stmt = select(User.id).where(User.email == email)
        return self._session.scalars(stmt).first() is not None

    def get_in_business(self, user_id: int, business_id: int) -> User | None:
        """Tenant-scoped fetch: returns None if the user is in another business."""
        stmt = select(User).where(User.id == user_id, User.business_id == business_id)
        return self._session.scalars(stmt).one_or_none()

    def list_by_business(self, business_id: int) -> list[User]:
        stmt = select(User).where(User.business_id == business_id).order_by(User.id)
        return list(self._session.scalars(stmt).all())
