"""Helpers for building authenticated API state in integration tests."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient


@dataclass
class Registered:
    business_id: int
    user_id: int
    email: str
    access: str
    refresh: str


def register_business(
    api: TestClient,
    *,
    email: str = "owner@shop.co",
    password: str = "sup3rsecret!",
    name: str = "Test Shop",
) -> Registered:
    resp = api.post(
        "/api/auth/register",
        json={
            "business_name": name,
            "category": "grocery",
            "contact_number": "+911234567890",
            "address": "1 Market Rd",
            "email": email,
            "password": password,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return Registered(
        business_id=body["business_id"],
        user_id=body["user"]["id"],
        email=email,
        access=body["tokens"]["access_token"],
        refresh=body["tokens"]["refresh_token"],
    )


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_product(
    api: TestClient,
    access: str,
    *,
    name: str = "Notebook",
    price: str = "50.00",
    sku: str = "SKU-1",
    category_id: int | None = None,
    description: str | None = None,
) -> dict:
    body: dict[str, object] = {"name": name, "price": price, "sku": sku}
    if category_id is not None:
        body["category_id"] = category_id
    if description is not None:
        body["description"] = description
    resp = api.post("/api/products", headers=auth_header(access), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def set_pin(api: TestClient, access: str, pin: str = "4321") -> None:
    resp = api.post("/api/business/me/pin", headers=auth_header(access), json={"pin": pin})
    assert resp.status_code == 204


def create_category(api: TestClient, access: str, name: str = "Groceries") -> dict:
    resp = api.post("/api/categories", headers=auth_header(access), json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


# A tiny but valid JPEG magic-number prefix; enough for the mock provider path.
FAKE_IMAGE = b"\xff\xd8\xff\xe0sample-bytes"


def generate_draft(
    api: TestClient,
    access: str,
    *,
    content: bytes = FAKE_IMAGE,
    content_type: str = "image/jpeg",
    request_key: str | None = None,
) -> object:
    files = {"file": ("product.jpg", content, content_type)}
    data: dict[str, str] = {}
    if request_key is not None:
        data["request_key"] = request_key
    return api.post(
        "/api/catalog-ai/drafts",
        headers=auth_header(access),
        files=files,
        data=data,
    )


def create_inventory(
    api: TestClient,
    access: str,
    product_id: int,
    *,
    quantity: int = 0,
    low_stock_threshold: int = 0,
) -> object:
    return api.post(
        "/api/inventory",
        headers=auth_header(access),
        json={
            "product_id": product_id,
            "quantity": quantity,
            "low_stock_threshold": low_stock_threshold,
        },
    )


def adjust_stock(
    api: TestClient,
    access: str,
    inventory_id: int,
    *,
    delta: int,
    movement_type: str = "MANUAL_ADJUSTMENT",
) -> object:
    return api.post(
        f"/api/inventory/{inventory_id}/adjust",
        headers=auth_header(access),
        json={"delta": delta, "movement_type": movement_type},
    )


def converse(api: TestClient, access: str, text: str) -> object:
    return api.post(
        "/api/conversation/message",
        headers=auth_header(access),
        json={"text": text},
    )


def create_customer(
    api: TestClient, access: str, *, name: str = "Asha", phone: str = "+919111111111"
) -> dict:
    resp = api.post(
        "/api/customers", headers=auth_header(access), json={"name": name, "phone": phone}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_order(api: TestClient, access: str, customer_id: int, items: list[dict]) -> object:
    return api.post(
        "/api/orders",
        headers=auth_header(access),
        json={"customer_id": customer_id, "items": items},
    )


def transition_order(api: TestClient, access: str, order_id: int, event: str) -> object:
    return api.post(
        f"/api/orders/{order_id}/transition",
        headers=auth_header(access),
        json={"event": event},
    )


def initiate_payment(
    api: TestClient, access: str, order_id: int, *, method: str = "ONLINE"
) -> object:
    return api.post(
        "/api/payments",
        headers=auth_header(access),
        json={"order_id": order_id, "method": method},
    )


def verify_payment(
    api: TestClient, access: str, payment_id: int, provider_payment_id: str
) -> object:
    return api.post(
        f"/api/payments/{payment_id}/verify",
        headers=auth_header(access),
        json={"provider_payment_id": provider_payment_id},
    )


def pay_order_online(api: TestClient, access: str, order_id: int, *, pid: str = "pay_ok_1") -> dict:
    """Confirmed order -> initiate online payment -> verify success. Returns payment."""
    payment = initiate_payment(api, access, order_id).json()  # type: ignore[attr-defined]
    return verify_payment(api, access, payment["id"], pid).json()  # type: ignore[attr-defined]


def generate_invoice(api: TestClient, access: str, order_id: int) -> object:
    return api.post("/api/invoices", headers=auth_header(access), json={"order_id": order_id})


def make_order(api: TestClient, access: str, product_id: int, customer_id: int, qty: int) -> int:
    order = create_order(
        api, access, customer_id, [{"product_id": product_id, "quantity": qty}]
    ).json()  # type: ignore[attr-defined]
    return order["id"]


def pay_existing_order(api: TestClient, access: str, order_id: int, *, pid: str) -> None:
    """Confirm then pay an existing order online with a unique provider payment id."""
    transition_order(api, access, order_id, "CONFIRM")
    pay_order_online(api, access, order_id, pid=pid)
