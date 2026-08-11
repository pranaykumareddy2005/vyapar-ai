"""Unit tests: RazorpayAdapter over a mocked HTTP transport (no live credentials)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from app.payment.adapters.razorpay import RazorpayAdapter
from app.payment.provider import (
    PaymentProviderConfigError,
    PaymentProviderInvalidResponse,
    PaymentProviderRateLimited,
    PaymentProviderTimeout,
    PaymentProviderUnavailable,
    ProviderPaymentStatus,
)


def _adapter(handler: object) -> RazorpayAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return RazorpayAdapter(key="rzp_key", secret="secret", client=client)


def test_create_payment_returns_order_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/orders")
        return httpx.Response(200, json={"id": "order_ABC", "amount": 10000, "currency": "INR"})

    adapter = _adapter(handler)
    init = adapter.create_payment(amount=Decimal("100.00"), currency="INR", reference="order-1")
    assert init.provider_order_id == "order_ABC"


def test_verify_maps_captured_to_success_and_paise_to_major() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "pay_1",
                "order_id": "order_ABC",
                "status": "captured",
                "amount": 10000,
                "currency": "INR",
            },
        )

    result = _adapter(handler).verify_payment(
        provider_payment_id="pay_1",
        provider_order_id="order_ABC",
        amount=Decimal("100.00"),
        currency="INR",
    )
    assert result.status is ProviderPaymentStatus.SUCCESS
    assert result.amount == Decimal("100.00")
    assert result.provider_order_id == "order_ABC"


def test_verify_failed_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "pay_1",
                "order_id": "o",
                "status": "failed",
                "amount": 10000,
                "currency": "INR",
            },
        )

    assert (
        _adapter(handler)
        .verify_payment(
            provider_payment_id="pay_1",
            provider_order_id="o",
            amount=Decimal("100.00"),
            currency="INR",
        )
        .status
        is ProviderPaymentStatus.FAILED
    )


def test_malformed_response_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "pay_1"})  # missing fields

    with pytest.raises(PaymentProviderInvalidResponse):
        _adapter(handler).verify_payment(
            provider_payment_id="pay_1", provider_order_id="o", amount=Decimal("1"), currency="INR"
        )


@pytest.mark.parametrize(
    ("code", "exc"),
    [
        (429, PaymentProviderRateLimited),
        (401, PaymentProviderConfigError),
        (403, PaymentProviderConfigError),
        (500, PaymentProviderUnavailable),
    ],
)
def test_http_errors_mapped(code: int, exc: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"error": "x"})

    with pytest.raises(exc):
        _adapter(handler).create_payment(amount=Decimal("1"), currency="INR", reference="r")


def test_timeout_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("t")

    with pytest.raises(PaymentProviderTimeout):
        _adapter(handler).create_payment(amount=Decimal("1"), currency="INR", reference="r")


def test_missing_credentials_rejected() -> None:
    with pytest.raises(PaymentProviderConfigError):
        RazorpayAdapter(key="", secret="")
