"""Security tests: auth, RBAC, and cross-tenant isolation for customers/orders."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_customer,
    create_inventory,
    create_order,
    create_product,
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


def _seed(api: TestClient, reg: object) -> dict:
    pid = create_product(api, reg.access, name="Notebook", sku="NB-S")["id"]  # type: ignore[attr-defined]
    create_inventory(api, reg.access, pid, quantity=10)  # type: ignore[attr-defined]
    cust = create_customer(api, reg.access)  # type: ignore[attr-defined]
    order = create_order(api, reg.access, cust["id"], [{"product_id": pid, "quantity": 1}]).json()  # type: ignore[attr-defined]
    return {"pid": pid, "cust": cust["id"], "order": order["id"]}


# --- auth / RBAC ------------------------------------------------------------


def test_unauthenticated_denied(api: TestClient) -> None:
    assert api.get("/api/customers").status_code == 401
    assert api.get("/api/orders").status_code == 401
    assert api.post("/api/orders", json={"customer_id": 1, "items": []}).status_code == 401


def test_admin_cannot_create_customer_or_order(api: TestClient) -> None:
    reg = register_business(api)
    seed = _seed(api, reg)
    admin = _role_token(api, reg.access, "ADMIN", "admin@shop.co")
    assert (
        api.post(
            "/api/customers", headers=auth_header(admin), json={"name": "X", "phone": "+91999"}
        ).status_code
        == 403
    )
    assert (
        create_order(
            api, admin, seed["cust"], [{"product_id": seed["pid"], "quantity": 1}]
        ).status_code
        == 403
    )
    assert transition_order(api, admin, seed["order"], "CONFIRM").status_code == 403


def test_employee_can_manage_orders(api: TestClient) -> None:
    reg = register_business(api)
    emp = _role_token(api, reg.access, "EMPLOYEE", "emp@shop.co")
    pid = create_product(api, emp, name="Pen", sku="PEN-1")["id"]
    create_inventory(api, emp, pid, quantity=5)
    cust = create_customer(api, emp, phone="+919222222222")
    order = create_order(api, emp, cust["id"], [{"product_id": pid, "quantity": 2}])
    assert order.status_code == 201
    assert transition_order(api, emp, order.json()["id"], "CONFIRM").status_code == 200


# --- cross-tenant / IDOR ----------------------------------------------------


def test_cross_tenant_customer_read(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_seed = _seed(api, b)
    assert (
        api.get(f"/api/customers/{b_seed['cust']}", headers=auth_header(a.access)).status_code
        == 404
    )


def test_cross_tenant_order_read(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_seed = _seed(api, b)
    assert (
        api.get(f"/api/orders/{b_seed['order']}", headers=auth_header(a.access)).status_code == 404
    )


def test_cross_tenant_order_transition(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_seed = _seed(api, b)
    resp = transition_order(api, a.access, b_seed["order"], "CONFIRM")
    assert resp.status_code == 404
    # B's order is untouched.
    assert (
        api.get(f"/api/orders/{b_seed['order']}", headers=auth_header(b.access)).json()["status"]
        == "CREATED"
    )


def test_cannot_order_with_foreign_customer(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_seed = _seed(api, b)
    a_pid = create_product(api, a.access, name="Notebook", sku="A-NB")["id"]
    create_inventory(api, a.access, a_pid, quantity=10)
    # A tries to place an order for B's customer.
    resp = create_order(api, a.access, b_seed["cust"], [{"product_id": a_pid, "quantity": 1}])
    assert resp.status_code == 404


def test_cannot_order_foreign_product(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_seed = _seed(api, b)
    a_cust = create_customer(api, a.access, phone="+919333333333")["id"]
    resp = create_order(api, a.access, a_cust, [{"product_id": b_seed["pid"], "quantity": 1}])
    assert resp.status_code == 422
