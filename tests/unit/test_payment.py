"""Unit tests: payment schema, state machine, and the deterministic mock provider."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.payment.models import (
    TERMINAL,
    VERIFIABLE_FROM,
    PaymentMethod,
    PaymentStatus,
)
from app.payment.provider import (
    MockPaymentProvider,
    PaymentProviderConfigError,
    PaymentProviderInvalidResponse,
    PaymentProviderTimeout,
    PaymentProviderUnavailable,
    ProviderPaymentStatus,
)
from app.payment.schemas import PaymentInitiate, PaymentVerify
from pydantic import ValidationError

# --- schema -----------------------------------------------------------------


def test_initiate_defaults_to_online() -> None:
    assert PaymentInitiate(order_id=1).method is PaymentMethod.ONLINE
    assert PaymentInitiate(order_id=1, method="COD").method is PaymentMethod.COD


def test_initiate_rejects_unknown_method() -> None:
    with pytest.raises(ValidationError):
        PaymentInitiate(order_id=1, method="CRYPTO")  # type: ignore[arg-type]


def test_verify_requires_provider_payment_id() -> None:
    with pytest.raises(ValidationError):
        PaymentVerify(provider_payment_id="")


def test_initiate_does_not_accept_amount() -> None:
    # A client-supplied amount is ignored (extra field), never trusted.
    p = PaymentInitiate.model_validate({"order_id": 1, "amount": "1.00"})
    assert "amount" not in p.model_dump()


# --- state machine ----------------------------------------------------------


def test_verifiable_and_terminal_sets() -> None:
    assert frozenset({PaymentStatus.CREATED, PaymentStatus.PENDING}) == VERIFIABLE_FROM
    assert (
        frozenset({PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.CANCELLED})
        == TERMINAL
    )
    # Success and failure are terminal - never re-verifiable (no SUCCESS->FAILED etc.).
    assert not (VERIFIABLE_FROM & TERMINAL)


# --- mock provider ----------------------------------------------------------


@pytest.fixture
def provider() -> MockPaymentProvider:
    return MockPaymentProvider()


def test_mock_create_is_deterministic(provider: MockPaymentProvider) -> None:
    a = provider.create_payment(amount=Decimal("100.00"), currency="INR", reference="order-1")
    b = provider.create_payment(amount=Decimal("100.00"), currency="INR", reference="order-1")
    assert a == b
    assert a.provider_order_id == "order_order-1"


def _verify(provider: MockPaymentProvider, pid: str) -> object:
    return provider.verify_payment(
        provider_payment_id=pid,
        provider_order_id="order_order-1",
        amount=Decimal("100.00"),
        currency="INR",
    )


def test_mock_success(provider: MockPaymentProvider) -> None:
    r = _verify(provider, "pay_ok_1")
    assert r.status is ProviderPaymentStatus.SUCCESS  # type: ignore[attr-defined]
    assert r.amount == Decimal("100.00")  # type: ignore[attr-defined]


def test_mock_pending_and_fail(provider: MockPaymentProvider) -> None:
    assert _verify(provider, "pay_pending_1").status is ProviderPaymentStatus.PENDING  # type: ignore[attr-defined]
    assert _verify(provider, "pay_fail_1").status is ProviderPaymentStatus.FAILED  # type: ignore[attr-defined]


def test_mock_amount_and_currency_mismatch(provider: MockPaymentProvider) -> None:
    assert _verify(provider, "pay_amount_1").amount == Decimal("101.00")  # type: ignore[attr-defined]
    assert _verify(provider, "pay_currency_1").currency == "USD"  # type: ignore[attr-defined]


def test_mock_order_reference_mismatch(provider: MockPaymentProvider) -> None:
    assert _verify(provider, "pay_order_1").provider_order_id == "order_someone_else"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("pid", "exc"),
    [
        ("pay_unavailable_1", PaymentProviderUnavailable),
        ("pay_timeout_1", PaymentProviderTimeout),
        ("pay_auth_1", PaymentProviderConfigError),
        ("pay_malformed_1", PaymentProviderInvalidResponse),
    ],
)
def test_mock_provider_failures(
    provider: MockPaymentProvider, pid: str, exc: type[Exception]
) -> None:
    with pytest.raises(exc):
        _verify(provider, pid)
