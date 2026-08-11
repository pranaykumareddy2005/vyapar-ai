"""Payment provider abstraction (the LLD "PaymentGateway") + deterministic mock.

The domain depends only on the :class:`PaymentProvider` protocol and the typed
result dataclasses below - never on a vendor SDK. Provider failures are an explicit
exception hierarchy so ``PaymentService`` can map them to controlled domain errors
and never leak raw provider details or secrets.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable


class ProviderPaymentStatus(enum.StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class ProviderInitiation:
    """Facts returned when a gateway payment/link is created."""

    provider_order_id: str
    payment_url: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderVerification:
    """Typed facts returned by the gateway for a payment - validated by the service."""

    provider_payment_id: str
    provider_order_id: str
    status: ProviderPaymentStatus
    amount: Decimal
    currency: str


# --- error hierarchy (infrastructure, never surfaced raw) -------------------


class PaymentProviderError(Exception):
    code = "payment_provider_error"


class PaymentProviderTimeout(PaymentProviderError):
    code = "payment_provider_timeout"


class PaymentProviderUnavailable(PaymentProviderError):
    code = "payment_provider_unavailable"


class PaymentProviderRateLimited(PaymentProviderError):
    code = "payment_provider_rate_limited"


class PaymentProviderConfigError(PaymentProviderError):
    code = "payment_provider_config_error"


class PaymentProviderInvalidResponse(PaymentProviderError):
    code = "payment_provider_invalid_response"


@runtime_checkable
class PaymentProvider(Protocol):
    """Vendor-neutral gateway seam. Returns typed facts; owns no application state."""

    name: str

    def create_payment(
        self, *, amount: Decimal, currency: str, reference: str
    ) -> ProviderInitiation: ...

    def verify_payment(
        self,
        *,
        provider_payment_id: str,
        provider_order_id: str,
        amount: Decimal,
        currency: str,
    ) -> ProviderVerification: ...


# --- deterministic mock -----------------------------------------------------


class MockPaymentProvider:
    """Deterministic gateway for dev/tests (no randomness, no credentials).

    ``create_payment`` returns a stable ``provider_order_id`` derived from the
    reference. ``verify_payment`` decides the outcome from the ``provider_payment_id``
    prefix so every scenario is reproducible:

    - ``pay_ok*``            -> SUCCESS with the expected amount/currency/order
    - ``pay_pending*``       -> PENDING
    - ``pay_fail*``          -> FAILED
    - ``pay_amount*``        -> SUCCESS but amount off by 1 (amount mismatch)
    - ``pay_currency*``      -> SUCCESS but currency USD (currency mismatch)
    - ``pay_order*``         -> SUCCESS but a different provider_order_id (ref mismatch)
    - ``pay_unavailable*``   -> provider unavailable
    - ``pay_timeout*``       -> provider timeout
    - ``pay_auth*``          -> provider config/auth error
    - ``pay_malformed*``     -> malformed provider response
    """

    name = "mock"

    def create_payment(
        self, *, amount: Decimal, currency: str, reference: str
    ) -> ProviderInitiation:
        provider_order_id = f"order_{reference}"
        return ProviderInitiation(
            provider_order_id=provider_order_id,
            payment_url=f"https://mock.pay/{provider_order_id}",
        )

    def verify_payment(
        self,
        *,
        provider_payment_id: str,
        provider_order_id: str,
        amount: Decimal,
        currency: str,
    ) -> ProviderVerification:
        pid = provider_payment_id
        if pid.startswith("pay_unavailable"):
            raise PaymentProviderUnavailable("mock: gateway unavailable")
        if pid.startswith("pay_timeout"):
            raise PaymentProviderTimeout("mock: gateway timeout")
        if pid.startswith("pay_auth"):
            raise PaymentProviderConfigError("mock: gateway auth failed")
        if pid.startswith("pay_malformed"):
            raise PaymentProviderInvalidResponse("mock: malformed gateway response")

        result_amount = amount
        result_currency = currency
        result_order = provider_order_id
        status = ProviderPaymentStatus.SUCCESS
        if pid.startswith("pay_pending"):
            status = ProviderPaymentStatus.PENDING
        elif pid.startswith("pay_fail"):
            status = ProviderPaymentStatus.FAILED
        elif pid.startswith("pay_amount"):
            result_amount = amount + Decimal("1.00")
        elif pid.startswith("pay_currency"):
            result_currency = "USD"
        elif pid.startswith("pay_order"):
            result_order = "order_someone_else"

        return ProviderVerification(
            provider_payment_id=pid,
            provider_order_id=result_order,
            status=status,
            amount=result_amount,
            currency=result_currency,
        )
