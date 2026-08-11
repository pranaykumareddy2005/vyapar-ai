"""Security tests: auth, RBAC, and cross-tenant isolation for invoices."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_customer,
    create_inventory,
    create_order,
    create_product,
    generate_invoice,
    pay_order_online,
    register_business,
    transition_order,
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


def _paid_order(api: TestClient, reg: object, *, sku: str = "NB-1") -> int:
    pid = create_product(api, reg.access, name="Notebook", sku=sku)["id"]  # type: ignore[attr-defined]
    create_inventory(api, reg.access, pid, quantity=10)  # type: ignore[attr-defined]
    cust = create_customer(api, reg.access, phone=f"+9199{sku}")["id"]  # type: ignore[attr-defined]
    order = create_order(api, reg.access, cust, [{"product_id": pid, "quantity": 1}]).json()  # type: ignore[attr-defined]
    transition_order(api, reg.access, order["id"], "CONFIRM")  # type: ignore[attr-defined]
    pay_order_online(api, reg.access, order["id"])  # type: ignore[attr-defined]
    return order["id"]


# --- auth / RBAC ------------------------------------------------------------


def test_unauthenticated_denied(api: TestClient) -> None:
    assert api.get("/api/invoices").status_code == 401
    assert api.post("/api/invoices", json={"order_id": 1}).status_code == 401
    assert api.get("/api/invoices/1/pdf").status_code == 401


def test_admin_cannot_generate(api: TestClient) -> None:
    reg = register_business(api)
    order_id = _paid_order(api, reg)
    admin = _role_token(api, reg.access, "ADMIN", "admin@shop.co")
    assert generate_invoice(api, admin, order_id).status_code == 403


def test_employee_can_generate(api: TestClient) -> None:
    reg = register_business(api)
    emp = _role_token(api, reg.access, "EMPLOYEE", "emp@shop.co")
    order_id = _paid_order(api, reg, sku="NB-E")
    assert generate_invoice(api, emp, order_id).status_code == 201


# --- cross-tenant / IDOR ----------------------------------------------------


def test_cross_tenant_invoice_read(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_order = _paid_order(api, b)
    b_inv = generate_invoice(api, b.access, b_order).json()
    assert api.get(f"/api/invoices/{b_inv['id']}", headers=auth_header(a.access)).status_code == 404


def test_cross_tenant_pdf_access(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_order = _paid_order(api, b)
    b_inv = generate_invoice(api, b.access, b_order).json()
    assert (
        api.get(f"/api/invoices/{b_inv['id']}/pdf", headers=auth_header(a.access)).status_code
        == 404
    )


def test_cross_tenant_generate_for_foreign_order(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_order = _paid_order(api, b)
    assert generate_invoice(api, a.access, b_order).status_code == 404
