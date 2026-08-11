"""Payment application service - owns payment rules and the state machine.

Payment success reaches the order's PAID state only through
``OrderService.transition(PAY)`` (never a direct Order write) and never touches
inventory. The server is authoritative over amount, currency, and provider
references; the client and the raw provider are not. Concurrency and duplicate
callbacks are made safe by a ``FOR UPDATE`` lock on the payment plus DB unique
constraints (one SUCCESS per order; one payment per provider payment id).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.events import EventBus, PaymentFailed, PaymentSucceeded, event_bus
from app.common.exceptions import ConflictError, NotFoundError
from app.order.models import OrderEvent, OrderStatus
from app.order.service import OrderService
from app.payment.errors import (
    PaymentMismatchError,
    PaymentProviderUnavailableError,
    PaymentStateError,
)
from app.payment.models import (
    VERIFIABLE_FROM,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.payment.provider import (
    PaymentProvider,
    PaymentProviderError,
    ProviderPaymentStatus,
)
from app.payment.repository import PaymentRepository

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(
        self,
        session: Session,
        payments: PaymentRepository,
        orders: OrderService,
        provider: PaymentProvider,
        *,
        currency: str,
        events: EventBus = event_bus,
    ) -> None:
        self._session = session
        self._payments = payments
        self._orders = orders
        self._provider = provider
        self._currency = currency
        self._events = events

    # --- queries ----------------------------------------------------------

    def get(self, business_id: int, payment_id: int) -> Payment:
        payment = self._payments.get(business_id, payment_id)
        if payment is None:
            raise NotFoundError("payment not found")
        return payment

    def list_payments(self, business_id: int) -> list[Payment]:
        return self._payments.list(business_id)

    # --- initiation -------------------------------------------------------

    def initiate(
        self,
        business_id: int,
        order_id: int,
        method: PaymentMethod,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[Payment, str | None]:
        """Create a payment attempt for a CONFIRMED order using the order's total.

        Returns the payment and, for online payments, an optional gateway URL.
        """
        order = self._orders.get_order(business_id, order_id)  # 404 if not this tenant
        if order.status is not OrderStatus.CONFIRMED:
            raise PaymentStateError("order is not awaiting payment")
        if self._payments.successful_exists_for_order(business_id, order_id):
            raise PaymentStateError("order already has a successful payment")

        if idempotency_key is not None:
            existing = self._payments.get_by_idempotency_key(business_id, idempotency_key)
            if existing is not None:
                return existing, None

        amount = order.total_amt
        payment_url: str | None = None
        provider_name = "cod"
        provider_order_id: str | None = None
        if method is PaymentMethod.ONLINE:
            try:
                init = self._provider.create_payment(
                    amount=amount, currency=self._currency, reference=f"order-{order_id}"
                )
            except PaymentProviderError as exc:
                logger.warning("payment provider create failed: %s", exc.code)
                raise PaymentProviderUnavailableError("payment gateway unavailable") from exc
            provider_name = self._provider.name
            provider_order_id = init.provider_order_id
            payment_url = init.payment_url

        try:
            payment = self._payments.add(
                Payment(
                    business_id=business_id,
                    order_id=order_id,
                    method=method,
                    amount=amount,
                    currency=self._currency,
                    status=PaymentStatus.CREATED,
                    provider=provider_name,
                    provider_order_id=provider_order_id,
                    idempotency_key=idempotency_key,
                )
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            if idempotency_key is not None:
                existing = self._payments.get_by_idempotency_key(business_id, idempotency_key)
                if existing is not None:
                    return existing, None
            raise ConflictError("duplicate payment initiation") from exc
        except Exception:
            self._session.rollback()
            raise
        self._session.refresh(payment)
        return payment, payment_url

    # --- verification (online) -------------------------------------------

    def verify(
        self,
        business_id: int,
        payment_id: int,
        provider_payment_id: str,
        *,
        actor_user_id: int | None = None,
    ) -> Payment:
        payment = self._payments.lock_for_update(business_id, payment_id)
        if payment is None:
            self._session.rollback()
            raise NotFoundError("payment not found")
        if payment.method is not PaymentMethod.ONLINE:
            self._session.rollback()
            raise PaymentStateError("not an online payment")
        if payment.status is PaymentStatus.SUCCESS:
            # Idempotent: duplicate verification of an already-successful payment.
            self._session.rollback()
            return payment
        if payment.status not in VERIFIABLE_FROM:
            self._session.rollback()
            raise PaymentStateError(f"cannot verify a {payment.status.value} payment")

        order = self._orders.get_order(business_id, payment.order_id)
        if order.status is not OrderStatus.CONFIRMED:
            self._session.rollback()
            raise PaymentStateError("order is not awaiting payment")

        try:
            result = self._provider.verify_payment(
                provider_payment_id=provider_payment_id,
                provider_order_id=payment.provider_order_id or "",
                amount=payment.amount,
                currency=payment.currency,
            )
        except PaymentProviderError as exc:
            # Transient gateway problem: do not mark FAILED (payment may still be
            # valid). Release the lock and surface a controlled error to retry.
            self._session.rollback()
            logger.warning("payment provider verify failed: %s", exc.code)
            raise PaymentProviderUnavailableError("payment gateway unavailable") from exc

        if result.status is ProviderPaymentStatus.PENDING:
            payment.status = PaymentStatus.PENDING
            self._commit()
            self._session.refresh(payment)
            return payment
        if result.status is ProviderPaymentStatus.FAILED:
            return self._fail(payment, "provider_failed", "gateway reported a failed payment")
        if result.provider_order_id != (payment.provider_order_id or ""):
            return self._fail(payment, "reference_mismatch", "provider order reference mismatch")
        if result.amount != payment.amount:
            return self._fail(
                payment, "amount_mismatch", "provider amount does not match the order total"
            )
        if result.currency != payment.currency:
            return self._fail(payment, "currency_mismatch", "provider currency mismatch")

        return self._succeed(payment, result.provider_payment_id, actor_user_id)

    # --- COD confirmation -------------------------------------------------

    def confirm_cod(
        self, business_id: int, payment_id: int, *, actor_user_id: int | None = None
    ) -> Payment:
        payment = self._payments.lock_for_update(business_id, payment_id)
        if payment is None:
            self._session.rollback()
            raise NotFoundError("payment not found")
        if payment.method is not PaymentMethod.COD:
            self._session.rollback()
            raise PaymentStateError("not a COD payment")
        if payment.status is PaymentStatus.SUCCESS:
            self._session.rollback()
            return payment
        if payment.status not in VERIFIABLE_FROM:
            self._session.rollback()
            raise PaymentStateError(f"cannot confirm a {payment.status.value} payment")
        order = self._orders.get_order(business_id, payment.order_id)
        if order.status is not OrderStatus.CONFIRMED:
            self._session.rollback()
            raise PaymentStateError("order is not awaiting payment")
        return self._succeed(payment, None, actor_user_id)

    # --- shared success/failure ------------------------------------------

    def _succeed(
        self, payment: Payment, provider_payment_id: str | None, actor_user_id: int | None
    ) -> Payment:
        try:
            payment.provider_payment_id = provider_payment_id
            payment.status = PaymentStatus.SUCCESS
            payment.verified_at = datetime.now(UTC)
            # The flush can already trip a unique index (duplicate provider payment
            # id, or a second SUCCESS for the order); the commit inside transition
            # can too. Both are caught here as a controlled conflict.
            self._session.flush()
            # Reaches PAID through the OrderService boundary; its single commit
            # persists the payment SUCCESS and the order PAID atomically.
            self._orders.transition(
                payment.business_id, payment.order_id, OrderEvent.PAY, actor_user_id=actor_user_id
            )
        except IntegrityError as exc:
            self._session.rollback()
            raise PaymentStateError(
                "order already has a successful payment or duplicate provider reference"
            ) from exc
        except ConflictError as exc:
            self._session.rollback()
            raise PaymentStateError("order already has a successful payment") from exc
        self._session.refresh(payment)
        self._events.publish(
            PaymentSucceeded(
                business_id=payment.business_id, order_id=payment.order_id, payment_id=payment.id
            )
        )
        return payment

    def _fail(self, payment: Payment, code: str, reason: str) -> Payment:
        payment.status = PaymentStatus.FAILED
        payment.failure_code = code
        payment.failure_reason = reason[:500]
        self._commit()
        self._session.refresh(payment)
        self._events.publish(
            PaymentFailed(
                business_id=payment.business_id,
                order_id=payment.order_id,
                payment_id=payment.id,
                failure_code=code,
            )
        )
        raise PaymentMismatchError(reason)

    def _commit(self) -> None:
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
