"""Payment persistence. Tenant-scoped by ``business_id``; persistence-only."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.payment.models import Payment, PaymentStatus


class PaymentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, payment: Payment) -> Payment:
        self._session.add(payment)
        self._session.flush()
        return payment

    def get(self, business_id: int, payment_id: int) -> Payment | None:
        stmt = select(Payment).where(Payment.id == payment_id, Payment.business_id == business_id)
        return self._session.scalars(stmt).one_or_none()

    def lock_for_update(self, business_id: int, payment_id: int) -> Payment | None:
        """Row-lock a payment (``SELECT ... FOR UPDATE``) so concurrent verifies of
        the same payment serialize; the lock is held until the transaction commits.
        """
        stmt = (
            select(Payment)
            .where(Payment.id == payment_id, Payment.business_id == business_id)
            .with_for_update()
        )
        return self._session.scalars(stmt).one_or_none()

    def get_by_idempotency_key(self, business_id: int, key: str) -> Payment | None:
        stmt = select(Payment).where(
            Payment.business_id == business_id, Payment.idempotency_key == key
        )
        return self._session.scalars(stmt).first()

    def successful_exists_for_order(self, business_id: int, order_id: int) -> bool:
        stmt = select(Payment.id).where(
            Payment.business_id == business_id,
            Payment.order_id == order_id,
            Payment.status == PaymentStatus.SUCCESS,
        )
        return self._session.scalars(stmt).first() is not None

    def list(self, business_id: int) -> list[Payment]:
        stmt = select(Payment).where(Payment.business_id == business_id).order_by(Payment.id.desc())
        return list(self._session.scalars(stmt).all())
