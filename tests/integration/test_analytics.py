"""Integration tests: analytics correctness, tenant isolation, RBAC (exact values)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_customer,
    create_inventory,
    create_product,
    make_order,
    pay_existing_order,
    register_business,
    transition_order,
)


def _seed_sales(api: TestClient, reg: object) -> dict:
    """Two PAID orders (120 + 80), one CONFIRMED-only (excluded), one CANCELLED."""
    pid = create_product(api, reg.access, name="Notebook", sku="NB-1", price="40.00")["id"]  # type: ignore[attr-defined]
    create_inventory(api, reg.access, pid, quantity=100)  # type: ignore[attr-defined]
    cust = create_customer(api, reg.access)["id"]  # type: ignore[attr-defined]
    o1 = make_order(api, reg.access, pid, cust, 3)  # 120
    pay_existing_order(api, reg.access, o1, pid="pay_a")
    o2 = make_order(api, reg.access, pid, cust, 2)  # 80
    pay_existing_order(api, reg.access, o2, pid="pay_b")
    o3 = make_order(api, reg.access, pid, cust, 1)  # confirmed only -> excluded
    transition_order(api, reg.access, o3, "CONFIRM")
    o4 = make_order(api, reg.access, pid, cust, 1)  # cancelled -> excluded
    transition_order(api, reg.access, o4, "CANCEL")
    return {"pid": pid}


def _role_token(api: TestClient, owner: str, role: str, email: str) -> str:
    api.post(
        "/api/auth/users",
        headers=auth_header(owner),
        json={"email": email, "password": "password1234", "role": role},
    )
    return api.post("/api/auth/login", json={"email": email, "password": "password1234"}).json()[
        "access_token"
    ]


# --- correctness ------------------------------------------------------------


def test_sales_revenue_counts_only_paid_states(api: TestClient) -> None:
    reg = register_business(api)
    _seed_sales(api, reg)
    body = api.get("/api/analytics/sales?period=all", headers=auth_header(reg.access)).json()
    assert body["order_count"] == 2  # only the two PAID orders
    assert body["revenue"] == "200.00"  # 120 + 80
    assert body["currency"] == "INR"


def test_top_products_units_from_paid_orders(api: TestClient) -> None:
    reg = register_business(api)
    _seed_sales(api, reg)
    body = api.get("/api/analytics/top-products", headers=auth_header(reg.access)).json()
    assert body[0]["product_name"] == "Notebook"
    assert body[0]["units_sold"] == 5  # 3 + 2 (confirmed/cancelled excluded)
    assert body[0]["revenue"] == "200.00"


def test_payment_totals_use_successful_payments(api: TestClient, db_session: object) -> None:
    from app.analytics.periods import Period
    from app.analytics.service import AnalyticsService
    from sqlalchemy.orm import Session

    reg = register_business(api)
    _seed_sales(api, reg)  # two successful payments: 120 + 80
    assert isinstance(db_session, Session)
    service = AnalyticsService(db_session, currency="INR", timezone="UTC")
    totals = service.payment_totals(reg.business_id, Period.ALL)
    assert totals.successful_count == 2  # only SUCCESS payments (Payment authority)
    assert str(totals.total) == "200.00"


def test_empty_business_returns_zeroes(api: TestClient) -> None:
    reg = register_business(api)
    body = api.get("/api/analytics/sales?period=all", headers=auth_header(reg.access)).json()
    assert body["order_count"] == 0
    assert body["revenue"] == "0.00"
    assert api.get("/api/analytics/top-products", headers=auth_header(reg.access)).json() == []


# --- tenant isolation -------------------------------------------------------


def test_analytics_are_tenant_scoped(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    _seed_sales(api, b)  # only B has sales
    a_body = api.get("/api/analytics/sales?period=all", headers=auth_header(a.access)).json()
    assert a_body["order_count"] == 0
    assert a_body["revenue"] == "0.00"


# --- RBAC (OWNER/ADMIN only, per SDD §5) ------------------------------------


def test_employee_denied_analytics(api: TestClient) -> None:
    reg = register_business(api)
    emp = _role_token(api, reg.access, "EMPLOYEE", "emp@shop.co")
    assert api.get("/api/analytics/sales", headers=auth_header(emp)).status_code == 403


def test_owner_and_admin_allowed(api: TestClient) -> None:
    reg = register_business(api)
    assert api.get("/api/analytics/sales", headers=auth_header(reg.access)).status_code == 200
    admin = _role_token(api, reg.access, "ADMIN", "admin@shop.co")
    assert api.get("/api/analytics/sales", headers=auth_header(admin)).status_code == 200


def test_unauthenticated_denied(api: TestClient) -> None:
    assert api.get("/api/analytics/sales").status_code == 401
