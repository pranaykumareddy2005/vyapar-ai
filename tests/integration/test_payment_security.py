"""Security tests: auth, RBAC, cross-tenant isolation, and provider-reference replay."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_customer,
    create_inventory,
    create_order,
    create_product,
    initiate_payment,
    register_business,
    transition_order,
    verify_payment,
)


def _role_token(api: TestClient, owner_access: str, role: str, email: str) -> str:
    api.post(
        "/api/auth/users",
        headers=auth_header(owner_access),
        json={"email": email, "password": "password1234", "role": role},
    )
    return api.post("/api/auth/login", json={"email": email, "password": "password1234"}).json()[
        "access_token"
    ]


def _confirmed_order(api: TestClient, reg: object, *, sku: str = "NB-1") -> dict:
    pid = create_product(api, reg.access, name="Notebook", sku=sku)["id"]  # type: ignore[attr-defined]
    create_inventory(api, reg.access, pid, quantity=10)  # type: ignore[attr-defined]
    cust = create_customer(api, reg.access, phone=f"+9199{sku}")["id"]  # type: ignore[attr-defined]
    order = create_order(api, reg.access, cust, [{"product_id": pid, "quantity": 1}]).json()  # type: ignore[attr-defined]
    transition_order(api, reg.access, order["id"], "CONFIRM")  # type: ignore[attr-defined]
    return {"order": order["id"], "pid": pid}


# --- auth / RBAC ------------------------------------------------------------


def test_unauthenticated_denied(api: TestClient) -> None:
    assert api.get("/api/payments").status_code == 401
    assert api.post("/api/payments", json={"order_id": 1}).status_code == 401
    assert api.post("/api/payments/1/verify", json={"provider_payment_id": "x"}).status_code == 401


def test_admin_cannot_initiate_or_verify(api: TestClient) -> None:
    reg = register_business(api)
    ctx = _confirmed_order(api, reg)
    admin = _role_token(api, reg.access, "ADMIN", "admin@shop.co")
    assert initiate_payment(api, admin, ctx["order"]).status_code == 403
    # (a payment exists via owner to verify against)
    payment = initiate_payment(api, reg.access, ctx["order"]).json()
    assert verify_payment(api, admin, payment["id"], "pay_ok_1").status_code == 403


def test_employee_can_pay(api: TestClient) -> None:
    reg = register_business(api)
    emp = _role_token(api, reg.access, "EMPLOYEE", "emp@shop.co")
    ctx = _confirmed_order(api, reg, sku="NB-E")
    payment = initiate_payment(api, emp, ctx["order"]).json()
    assert verify_payment(api, emp, payment["id"], "pay_ok_1").json()["status"] == "SUCCESS"


# --- cross-tenant / IDOR ----------------------------------------------------


def test_cross_tenant_payment_read(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_ctx = _confirmed_order(api, b)
    b_payment = initiate_payment(api, b.access, b_ctx["order"]).json()
    assert (
        api.get(f"/api/payments/{b_payment['id']}", headers=auth_header(a.access)).status_code
        == 404
    )


def test_cross_tenant_verify(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_ctx = _confirmed_order(api, b)
    b_payment = initiate_payment(api, b.access, b_ctx["order"]).json()
    resp = verify_payment(api, a.access, b_payment["id"], "pay_ok_1")
    assert resp.status_code == 404
    # B's order remains unpaid.
    assert (
        api.get(f"/api/orders/{b_ctx['order']}", headers=auth_header(b.access)).json()["status"]
        == "CONFIRMED"
    )


def test_cross_tenant_initiate_for_foreign_order(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_ctx = _confirmed_order(api, b)
    assert initiate_payment(api, a.access, b_ctx["order"]).status_code == 404


def test_provider_payment_id_cannot_be_replayed(api: TestClient) -> None:
    # A provider payment id that already backs one successful payment cannot be
    # reused for a different order (unique provider_payment_id).
    reg = register_business(api)
    c1 = _confirmed_order(api, reg, sku="NB-A")
    c2 = _confirmed_order(api, reg, sku="NB-B")
    p1 = initiate_payment(api, reg.access, c1["order"]).json()
    assert verify_payment(api, reg.access, p1["id"], "pay_ok_shared").json()["status"] == "SUCCESS"
    p2 = initiate_payment(api, reg.access, c2["order"]).json()
    replay = verify_payment(api, reg.access, p2["id"], "pay_ok_shared")
    assert replay.status_code in (409, 422)
    assert (
        api.get(f"/api/orders/{c2['order']}", headers=auth_header(reg.access)).json()["status"]
        == "CONFIRMED"
    )
