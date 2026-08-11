"""Catalog security: cross-tenant isolation, RBAC, unauthorized access, leaks."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_product,
    register_business,
    set_pin,
)


def _two_businesses(api: TestClient) -> tuple:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    return a, b


# --- cross-tenant product access -------------------------------------------


def test_cannot_read_other_business_product(api: TestClient) -> None:
    a, b = _two_businesses(api)
    b_prod = create_product(api, b.access, sku="B-1")
    resp = api.get(f"/api/products/{b_prod['id']}", headers=auth_header(a.access))
    assert resp.status_code == 404


def test_cannot_update_other_business_product(api: TestClient) -> None:
    a, b = _two_businesses(api)
    b_prod = create_product(api, b.access, sku="B-2")
    resp = api.patch(
        f"/api/products/{b_prod['id']}",
        headers=auth_header(a.access),
        json={"name": "Hacked"},
    )
    assert resp.status_code == 404


def test_cannot_delete_other_business_product(api: TestClient) -> None:
    a, b = _two_businesses(api)
    set_pin(api, a.access, "4321")
    b_prod = create_product(api, b.access, sku="B-3")
    resp = api.delete(
        f"/api/products/{b_prod['id']}",
        headers={**auth_header(a.access), "X-Business-PIN": "4321"},
    )
    assert resp.status_code == 404
    # And B's product is untouched / still active for B.
    still = api.get(f"/api/products/{b_prod['id']}", headers=auth_header(b.access))
    assert still.status_code == 200


def test_cannot_list_other_business_images(api: TestClient) -> None:
    a, b = _two_businesses(api)
    b_prod = create_product(api, b.access, sku="B-4")
    api.post(
        f"/api/products/{b_prod['id']}/images",
        headers=auth_header(b.access),
        files={"file": ("p.jpg", b"bytes", "image/jpeg")},
    )
    resp = api.get(f"/api/products/{b_prod['id']}/images", headers=auth_header(a.access))
    assert resp.status_code == 404


def test_listing_is_tenant_scoped(api: TestClient) -> None:
    a, b = _two_businesses(api)
    create_product(api, a.access, sku="A-ONLY")
    create_product(api, b.access, sku="B-ONLY")
    listing = api.get("/api/products", headers=auth_header(a.access)).json()
    assert {p["sku"] for p in listing} == {"A-ONLY"}


# --- unauthorized -----------------------------------------------------------


def test_unauthorized_cannot_list_products(api: TestClient) -> None:
    resp = api.get("/api/products")
    assert resp.status_code == 401


def test_unauthorized_cannot_create_product(api: TestClient) -> None:
    resp = api.post("/api/products", json={"name": "X", "price": "1.00", "sku": "Z"})
    assert resp.status_code == 401


# --- RBAC -------------------------------------------------------------------


def test_employee_can_create_product(api: TestClient) -> None:
    reg = register_business(api)
    api.post(
        "/api/auth/users",
        headers=auth_header(reg.access),
        json={"email": "emp@shop.co", "password": "employeepass1", "role": "EMPLOYEE"},
    )
    emp = api.post(
        "/api/auth/login", json={"email": "emp@shop.co", "password": "employeepass1"}
    ).json()["access_token"]
    resp = api.post(
        "/api/products",
        headers=auth_header(emp),
        json={"name": "EmpProduct", "price": "3.00", "sku": "EMP-1"},
    )
    assert resp.status_code == 201


def test_admin_role_denied_catalog_mutation(api: TestClient) -> None:
    reg = register_business(api)
    api.post(
        "/api/auth/users",
        headers=auth_header(reg.access),
        json={"email": "admin@shop.co", "password": "adminpass123", "role": "ADMIN"},
    )
    admin = api.post(
        "/api/auth/login", json={"email": "admin@shop.co", "password": "adminpass123"}
    ).json()["access_token"]
    resp = api.post(
        "/api/products",
        headers=auth_header(admin),
        json={"name": "X", "price": "1.00", "sku": "ADM-1"},
    )
    assert resp.status_code == 403  # ADMIN is not an OWNER/EMPLOYEE catalog mutator
