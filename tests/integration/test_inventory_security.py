"""Security tests: auth, RBAC, and cross-tenant isolation for inventory (§6, §17)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    adjust_stock,
    auth_header,
    create_inventory,
    create_product,
    register_business,
)


def _two(api: TestClient) -> tuple:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    return a, b


def _role_token(api: TestClient, owner_access: str, role: str, email: str) -> str:
    api.post(
        "/api/auth/users",
        headers=auth_header(owner_access),
        json={"email": email, "password": "password1234", "role": role},
    )
    return api.post("/api/auth/login", json={"email": email, "password": "password1234"}).json()[
        "access_token"
    ]


def _inv_for(api: TestClient, reg: object, *, sku: str, qty: int = 10) -> int:
    pid = create_product(api, reg.access, sku=sku)["id"]  # type: ignore[attr-defined]
    return create_inventory(api, reg.access, pid, quantity=qty).json()["id"]  # type: ignore[attr-defined]


# --- unauthorized -----------------------------------------------------------


def test_unauthorized_cannot_list_inventory(api: TestClient) -> None:
    assert api.get("/api/inventory").status_code == 401


def test_unauthorized_cannot_create_inventory(api: TestClient) -> None:
    assert api.post("/api/inventory", json={"product_id": 1}).status_code == 401


def test_unauthorized_cannot_adjust(api: TestClient) -> None:
    assert (
        api.post(
            "/api/inventory/1/adjust", json={"delta": 1, "movement_type": "RESTOCK"}
        ).status_code
        == 401
    )


# --- RBAC -------------------------------------------------------------------


def test_admin_cannot_create_inventory(api: TestClient) -> None:
    reg = register_business(api)
    pid = create_product(api, reg.access, sku="ADM-1")["id"]
    admin = _role_token(api, reg.access, "ADMIN", "admin@shop.co")
    resp = create_inventory(api, admin, pid)
    assert resp.status_code == 403


def test_admin_cannot_adjust(api: TestClient) -> None:
    reg = register_business(api)
    inv_id = _inv_for(api, reg, sku="ADM-2")
    admin = _role_token(api, reg.access, "ADMIN", "admin2@shop.co")
    resp = adjust_stock(api, admin, inv_id, delta=5, movement_type="RESTOCK")
    assert resp.status_code == 403


def test_employee_can_adjust(api: TestClient) -> None:
    reg = register_business(api)
    inv_id = _inv_for(api, reg, sku="EMP-1")
    emp = _role_token(api, reg.access, "EMPLOYEE", "emp@shop.co")
    resp = adjust_stock(api, emp, inv_id, delta=5, movement_type="RESTOCK")
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 15


# --- cross-tenant isolation -------------------------------------------------


def test_cannot_read_other_business_inventory(api: TestClient) -> None:
    a, b = _two(api)
    b_inv = _inv_for(api, b, sku="B-1")
    assert api.get(f"/api/inventory/{b_inv}", headers=auth_header(a.access)).status_code == 404


def test_cannot_adjust_other_business_inventory(api: TestClient) -> None:
    a, b = _two(api)
    b_inv = _inv_for(api, b, sku="B-2", qty=10)
    resp = adjust_stock(api, a.access, b_inv, delta=-1, movement_type="SALE")
    assert resp.status_code == 404
    # B's stock is untouched.
    assert (
        api.get(f"/api/inventory/{b_inv}", headers=auth_header(b.access)).json()["quantity"] == 10
    )


def test_cannot_update_other_business_threshold(api: TestClient) -> None:
    a, b = _two(api)
    b_inv = _inv_for(api, b, sku="B-3")
    resp = api.patch(
        f"/api/inventory/{b_inv}",
        headers=auth_header(a.access),
        json={"low_stock_threshold": 99},
    )
    assert resp.status_code == 404


def test_cannot_read_other_business_movements(api: TestClient) -> None:
    a, b = _two(api)
    b_inv = _inv_for(api, b, sku="B-4")
    adjust_stock(api, b.access, b_inv, delta=1, movement_type="RESTOCK")
    resp = api.get(f"/api/inventory/{b_inv}/movements", headers=auth_header(a.access))
    assert resp.status_code == 404


def test_cannot_create_inventory_for_foreign_product(api: TestClient) -> None:
    a, b = _two(api)
    b_pid = create_product(api, b.access, sku="B-PROD")["id"]
    resp = create_inventory(api, a.access, b_pid)
    assert resp.status_code == 404
