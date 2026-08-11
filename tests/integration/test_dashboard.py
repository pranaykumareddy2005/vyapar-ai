"""Integration tests: dashboard KPI composition, tenant isolation, RBAC."""

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


def _seed(api: TestClient, reg: object) -> None:
    pid = create_product(api, reg.access, name="Notebook", sku="NB-1", price="40.00")["id"]  # type: ignore[attr-defined]
    # Enough stock to confirm the order, but low (<= threshold) afterwards.
    create_inventory(api, reg.access, pid, quantity=4, low_stock_threshold=5)  # type: ignore[attr-defined]
    cust = create_customer(api, reg.access)["id"]  # type: ignore[attr-defined]
    o1 = make_order(api, reg.access, pid, cust, 3)  # 120, paid
    pay_existing_order(api, reg.access, o1, pid="pay_a")
    o2 = make_order(api, reg.access, pid, cust, 1)  # confirmed only
    transition_order(api, reg.access, o2, "CONFIRM")


def _role_token(api: TestClient, owner: str, role: str, email: str) -> str:
    api.post(
        "/api/auth/users",
        headers=auth_header(owner),
        json={"email": email, "password": "password1234", "role": role},
    )
    return api.post("/api/auth/login", json={"email": email, "password": "password1234"}).json()[
        "access_token"
    ]


def test_dashboard_summary_kpis(api: TestClient) -> None:
    reg = register_business(api)
    _seed(api, reg)
    body = api.get("/api/dashboard/summary", headers=auth_header(reg.access)).json()
    assert body["sales_today"]["revenue"] == "120.00"
    assert body["sales_today"]["order_count"] == 1
    assert body["sales_month"]["revenue"] == "120.00"
    assert body["order_counts"]["PAID"] == 1
    assert body["order_counts"]["CONFIRMED"] == 1
    assert body["low_stock_count"] == 1  # inventory qty 1 <= threshold 5
    assert body["top_products"][0]["product_name"] == "Notebook"
    assert body["top_products"][0]["units_sold"] == 3
    assert len(body["recent_orders"]) == 2
    assert body["unread_notifications"] == 0  # listener disabled in tests


def test_dashboard_empty_business(api: TestClient) -> None:
    reg = register_business(api)
    body = api.get("/api/dashboard/summary", headers=auth_header(reg.access)).json()
    assert body["sales_today"]["revenue"] == "0.00"
    assert body["low_stock_count"] == 0
    assert body["top_products"] == []
    assert body["recent_orders"] == []


def test_dashboard_tenant_scoped(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    _seed(api, b)
    a_body = api.get("/api/dashboard/summary", headers=auth_header(a.access)).json()
    assert a_body["sales_today"]["revenue"] == "0.00"
    assert a_body["recent_orders"] == []


def test_dashboard_rbac(api: TestClient) -> None:
    reg = register_business(api)
    assert api.get("/api/dashboard/summary").status_code == 401
    emp = _role_token(api, reg.access, "EMPLOYEE", "emp@shop.co")
    assert api.get("/api/dashboard/summary", headers=auth_header(emp)).status_code == 403
    assert api.get("/api/dashboard/summary", headers=auth_header(reg.access)).status_code == 200
