"""Razorpay adapter - realizes :class:`PaymentProvider` over the Razorpay REST API.

Only this file knows Razorpay's wire format (orders + payments endpoints, HTTP
Basic auth, amounts in paise). It returns typed :class:`ProviderVerification`
facts; ``PaymentService`` does all amount/currency/reference validation. Provider
errors map to the neutral exception hierarchy.

Live validation status: exercised via a mocked HTTP transport. A real Razorpay
API request has NOT been executed in this environment (no live credentials), and
gateway-signature/webhook verification is therefore not live-verified either.
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from app.payment.provider import (
    PaymentProviderConfigError,
    PaymentProviderInvalidResponse,
    PaymentProviderRateLimited,
    PaymentProviderTimeout,
    PaymentProviderUnavailable,
    ProviderInitiation,
    ProviderPaymentStatus,
    ProviderVerification,
)

_STATUS_MAP = {
    "captured": ProviderPaymentStatus.SUCCESS,
    "authorized": ProviderPaymentStatus.SUCCESS,
    "created": ProviderPaymentStatus.PENDING,
    "pending": ProviderPaymentStatus.PENDING,
    "failed": ProviderPaymentStatus.FAILED,
    "refunded": ProviderPaymentStatus.FAILED,
}


def _to_major(amount_paise: int) -> Decimal:
    return (Decimal(amount_paise) / Decimal(100)).quantize(Decimal("0.01"))


def _to_minor(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


class RazorpayAdapter:
    name = "razorpay"

    def __init__(
        self,
        *,
        key: str,
        secret: str,
        api_base: str = "https://api.razorpay.com/v1",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not key or not secret:
            raise PaymentProviderConfigError("RZP_KEY/RZP_SECRET are required for razorpay")
        self._base = api_base.rstrip("/")
        self._auth = (key, secret)
        self._client = client or httpx.Client(timeout=timeout)

    def create_payment(
        self, *, amount: Decimal, currency: str, reference: str
    ) -> ProviderInitiation:
        body = {
            "amount": _to_minor(amount),
            "currency": currency,
            "receipt": reference,
            "payment_capture": 1,
        }
        data = self._request("POST", "/orders", json=body)
        order_id = data.get("id")
        if not order_id:
            raise PaymentProviderInvalidResponse("razorpay: missing order id")
        return ProviderInitiation(provider_order_id=str(order_id))

    def verify_payment(
        self,
        *,
        provider_payment_id: str,
        provider_order_id: str,
        amount: Decimal,
        currency: str,
    ) -> ProviderVerification:
        data = self._request("GET", f"/payments/{provider_payment_id}")
        try:
            raw_status = str(data["status"])
            status = _STATUS_MAP.get(raw_status, ProviderPaymentStatus.FAILED)
            return ProviderVerification(
                provider_payment_id=str(data["id"]),
                provider_order_id=str(data.get("order_id", "")),
                status=status,
                amount=_to_major(int(str(data["amount"]))),
                currency=str(data["currency"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentProviderInvalidResponse(f"razorpay: bad payment payload: {exc}") from exc

    def _request(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> dict[str, object]:
        try:
            response = self._client.request(
                method, f"{self._base}{path}", auth=self._auth, json=json
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise PaymentProviderTimeout(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 429:
                raise PaymentProviderRateLimited(str(exc)) from exc
            if code in (401, 403):
                raise PaymentProviderConfigError(f"razorpay auth failed ({code})") from exc
            raise PaymentProviderUnavailable(f"razorpay returned {code}") from exc
        except httpx.HTTPError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentProviderInvalidResponse("razorpay: non-JSON response") from exc
        if not isinstance(payload, dict):
            raise PaymentProviderInvalidResponse("razorpay: unexpected response shape")
        return payload
