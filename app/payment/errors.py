"""Payment domain errors surfaced at the API (never raw provider exceptions)."""

from __future__ import annotations

from app.common.exceptions import ConflictError, DomainError


class PaymentMismatchError(DomainError):
    """Provider amount/currency/reference did not match the order/payment."""

    status_code = 422
    code = "payment_mismatch"


class PaymentProviderUnavailableError(DomainError):
    """The gateway could not be reached or returned an unusable response."""

    status_code = 502
    code = "payment_provider_unavailable"


class PaymentStateError(ConflictError):
    """Invalid payment transition or duplicate/already-processed payment."""

    code = "payment_state_error"
