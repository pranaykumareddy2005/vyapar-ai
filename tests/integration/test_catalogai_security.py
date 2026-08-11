"""Security tests: cross-tenant isolation, RBAC, and auth for catalog-ai (§8, §9)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    generate_draft,
    register_business,
)


def _two(api: TestClient) -> tuple:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    return a, b


def _employee_token(api: TestClient, owner_access: str, role: str, email: str) -> str:
    api.post(
        "/api/auth/users",
        headers=auth_header(owner_access),
        json={"email": email, "password": "password1234", "role": role},
    )
    return api.post("/api/auth/login", json={"email": email, "password": "password1234"}).json()[
        "access_token"
    ]


# --- cross-tenant isolation -------------------------------------------------


def test_cannot_read_other_business_draft(api: TestClient) -> None:
    a, b = _two(api)
    b_draft = generate_draft(api, b.access).json()["id"]
    resp = api.get(f"/api/catalog-ai/drafts/{b_draft}", headers=auth_header(a.access))
    assert resp.status_code == 404


def test_cannot_edit_other_business_draft(api: TestClient) -> None:
    a, b = _two(api)
    b_draft = generate_draft(api, b.access).json()["id"]
    resp = api.patch(
        f"/api/catalog-ai/drafts/{b_draft}",
        headers=auth_header(a.access),
        json={"name": "Hacked"},
    )
    assert resp.status_code == 404


def test_cannot_approve_other_business_draft(api: TestClient) -> None:
    a, b = _two(api)
    b_draft = generate_draft(api, b.access).json()["id"]
    resp = api.post(
        f"/api/catalog-ai/drafts/{b_draft}/approve",
        headers=auth_header(a.access),
        json={"sku": "H-1", "price": "5.00"},
    )
    assert resp.status_code == 404
    # And nothing was created in either business.
    assert api.get("/api/products", headers=auth_header(a.access)).json() == []
    assert api.get("/api/products", headers=auth_header(b.access)).json() == []


def test_cannot_reject_other_business_draft(api: TestClient) -> None:
    a, b = _two(api)
    b_draft = generate_draft(api, b.access).json()["id"]
    resp = api.post(f"/api/catalog-ai/drafts/{b_draft}/reject", headers=auth_header(a.access))
    assert resp.status_code == 404


def test_draft_listing_is_tenant_scoped(api: TestClient) -> None:
    a, b = _two(api)
    generate_draft(api, a.access)
    generate_draft(api, b.access)
    a_list = api.get("/api/catalog-ai/drafts", headers=auth_header(a.access)).json()
    assert all(d["business_id"] == a.business_id for d in a_list)
    assert len(a_list) == 1


# --- unauthorized -----------------------------------------------------------


def test_unauthorized_cannot_generate(api: TestClient) -> None:
    resp = api.post(
        "/api/catalog-ai/drafts",
        files={"file": ("p.jpg", b"bytes", "image/jpeg")},
    )
    assert resp.status_code == 401


def test_unauthorized_cannot_approve(api: TestClient) -> None:
    resp = api.post("/api/catalog-ai/drafts/1/approve")
    assert resp.status_code == 401


# --- RBAC -------------------------------------------------------------------


def test_admin_role_cannot_generate(api: TestClient) -> None:
    reg = register_business(api)
    admin = _employee_token(api, reg.access, "ADMIN", "admin@shop.co")
    resp = generate_draft(api, admin)
    assert resp.status_code == 403


def test_admin_role_cannot_approve(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    admin = _employee_token(api, reg.access, "ADMIN", "admin2@shop.co")
    resp = api.post(
        f"/api/catalog-ai/drafts/{draft_id}/approve",
        headers=auth_header(admin),
        json={"sku": "A-1", "price": "1.00"},
    )
    assert resp.status_code == 403


def test_employee_can_run_full_flow(api: TestClient) -> None:
    reg = register_business(api)
    emp = _employee_token(api, reg.access, "EMPLOYEE", "emp@shop.co")
    draft_id = generate_draft(api, emp).json()["id"]
    resp = api.post(
        f"/api/catalog-ai/drafts/{draft_id}/approve",
        headers=auth_header(emp),
        json={"sku": "EMP-1", "price": "2.00"},
    )
    assert resp.status_code == 201
