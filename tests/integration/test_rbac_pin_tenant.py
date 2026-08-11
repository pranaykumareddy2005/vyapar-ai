"""RBAC, Business PIN step-up, tenant isolation / IDOR, and secret exposure.

Covers SRS security test checklist items 6-13.
"""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from tests.integration.helpers import auth_header, register_business


def _make_employee(api: TestClient, owner_access: str) -> str:
    created = api.post(
        "/api/auth/users",
        headers=auth_header(owner_access),
        json={"email": "emp@shop.co", "password": "employeepass1", "role": "EMPLOYEE"},
    )
    assert created.status_code == 201, created.text
    login = api.post("/api/auth/login", json={"email": "emp@shop.co", "password": "employeepass1"})
    assert login.status_code == 200
    return login.json()["access_token"]


# --- RBAC (#6, #7) ----------------------------------------------------------


def test_owner_can_update_profile(api: TestClient) -> None:
    reg = register_business(api)
    resp = api.patch("/api/business/me", headers=auth_header(reg.access), json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_employee_forbidden_from_owner_action(api: TestClient) -> None:  # #7 denied
    reg = register_business(api)
    emp_access = _make_employee(api, reg.access)
    resp = api.patch("/api/business/me", headers=auth_header(emp_access), json={"name": "Hacked"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "authorization_error"


def test_employee_cannot_create_users(api: TestClient) -> None:  # #7 denied
    reg = register_business(api)
    emp_access = _make_employee(api, reg.access)
    resp = api.post(
        "/api/auth/users",
        headers=auth_header(emp_access),
        json={"email": "x@shop.co", "password": "anotherpass1", "role": "EMPLOYEE"},
    )
    assert resp.status_code == 403


def test_employee_allowed_read_own_business(api: TestClient) -> None:  # #7 allowed
    reg = register_business(api)
    emp_access = _make_employee(api, reg.access)
    resp = api.get("/api/business/me", headers=auth_header(emp_access))
    assert resp.status_code == 200


# --- Business PIN step-up (#8, #9) ------------------------------------------


def _set_pin(api: TestClient, access: str, pin: str = "4321") -> None:
    resp = api.post("/api/business/me/pin", headers=auth_header(access), json={"pin": pin})
    assert resp.status_code == 204


def test_payment_pref_change_requires_correct_pin(api: TestClient) -> None:  # #8
    reg = register_business(api)
    _set_pin(api, reg.access, "4321")
    resp = api.put(
        "/api/business/me/payment-preferences",
        headers={**auth_header(reg.access), "X-Business-PIN": "4321"},
        json={"payment_preference": "ONLINE"},
    )
    assert resp.status_code == 200
    assert resp.json()["payment_preference"] == "ONLINE"


def test_payment_pref_change_wrong_pin_denied(api: TestClient) -> None:  # #9
    reg = register_business(api)
    _set_pin(api, reg.access, "4321")
    resp = api.put(
        "/api/business/me/payment-preferences",
        headers={**auth_header(reg.access), "X-Business-PIN": "0000"},
        json={"payment_preference": "ONLINE"},
    )
    assert resp.status_code == 403


def test_payment_pref_change_missing_pin_denied(api: TestClient) -> None:  # #9
    reg = register_business(api)
    _set_pin(api, reg.access, "4321")
    resp = api.put(
        "/api/business/me/payment-preferences",
        headers=auth_header(reg.access),
        json={"payment_preference": "ONLINE"},
    )
    assert resp.status_code == 403


# --- Tenant isolation / IDOR (#10, #11) -------------------------------------


def test_cross_tenant_user_read_is_404(api: TestClient) -> None:  # #10, #11
    a = register_business(api, email="a-owner@shop.co", name="Shop A")
    b = register_business(api, email="b-owner@shop.co", name="Shop B")
    # A tries to read B's user by id (IDOR): must not succeed or leak existence.
    resp = api.get(f"/api/auth/users/{b.user_id}", headers=auth_header(a.access))
    assert resp.status_code == 404


def test_user_list_scoped_to_own_business(api: TestClient) -> None:  # #10
    a = register_business(api, email="a2-owner@shop.co", name="Shop A")
    register_business(api, email="b2-owner@shop.co", name="Shop B")
    resp = api.get("/api/auth/users", headers=auth_header(a.access))
    assert resp.status_code == 200
    ids = {u["id"] for u in resp.json()}
    assert ids == {a.user_id}  # only A's own user


def test_whatsapp_number_cannot_be_double_linked(api: TestClient) -> None:
    a = register_business(api, email="a3@shop.co", name="Shop A")
    b = register_business(api, email="b3@shop.co", name="Shop B")
    number = "+919999000011"
    r1 = api.put(
        "/api/business/me/whatsapp",
        headers=auth_header(a.access),
        json={"whatsapp_number": number},
    )
    assert r1.status_code == 200
    r2 = api.put(
        "/api/business/me/whatsapp",
        headers=auth_header(b.access),
        json={"whatsapp_number": number},
    )
    assert r2.status_code == 409


# --- Secret exposure / logging (#12, #13) -----------------------------------


def test_business_response_hides_pin_hash(api: TestClient) -> None:  # #12
    reg = register_business(api)
    _set_pin(api, reg.access, "4321")
    resp = api.get("/api/business/me", headers=auth_header(reg.access))
    body = resp.json()
    assert body["pin_set"] is True
    assert "pin_hash" not in body
    assert "pin" not in body


def test_pin_not_logged(api: TestClient, caplog) -> None:  # #13
    reg = register_business(api)
    secret_pin = "4321"
    _set_pin(api, reg.access, secret_pin)
    with caplog.at_level(logging.DEBUG):
        api.put(
            "/api/business/me/payment-preferences",
            headers={**auth_header(reg.access), "X-Business-PIN": secret_pin},
            json={"payment_preference": "COD"},
        )
    assert secret_pin not in caplog.text
