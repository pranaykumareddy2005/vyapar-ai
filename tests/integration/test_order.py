"""Integration tests: order creation, totals, lifecycle, and inventory integration."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.common.events import OrderCancelled, OrderConfirmed, event_bus
from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_customer,
    create_inventory,
    create_order,
    create_product,
    pay_order_online,
    register_business,
    set_pin,
    transition_order,
)


@pytest.fixture
def captured_order_events() -> Iterator[list]:
    events: list = []
    event_bus.subscribe(OrderConfirmed, events.append)
    event_bus.subscribe(OrderCancelled, events.append)
    try:
        yield events
    finally:
        event_bus.clear()


def _seed(api: TestClient, *, price: str = "40.00", qty: int = 10) -> dict:
    reg = register_business(api)
    pid = create_product(api, reg.access, name="Notebook", sku="NB-1", price=price)["id"]
    inv_id = create_inventory(api, reg.access, pid, quantity=qty).json()["id"]
    cust = create_customer(api, reg.access)
    return {"reg": reg, "pid": pid, "inv_id": inv_id, "cust": cust["id"]}


def _stock(api: TestClient, access: str, inv_id: int) -> int:
    return api.get(f"/api/inventory/{inv_id}", headers=auth_header(access)).json()["quantity"]


# --- creation & totals ------------------------------------------------------


def test_create_order_snapshots_and_totals(api: TestClient) -> None:
    ctx = _seed(api, price="40.00")
    resp = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 3}]
    )
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["status"] == "CREATED"
    assert order["items"][0]["unit_price"] == "40.00"
    assert order["items"][0]["product_name"] == "Notebook"
    assert order["items"][0]["line_total"] == "120.00"
    assert order["total"] == "120.00"  # default tax rate 0


def test_create_order_ignores_client_price(api: TestClient) -> None:
    ctx = _seed(api, price="40.00")
    # Even if the client injects a bogus price/total, the schema ignores it and the
    # server snapshots from the catalog.
    resp = api.post(
        "/api/orders",
        headers=auth_header(ctx["reg"].access),
        json={
            "customer_id": ctx["cust"],
            "items": [{"product_id": ctx["pid"], "quantity": 2, "unit_price": "1.00"}],
            "total": "1.00",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["total"] == "80.00"


def test_create_order_foreign_customer_404(api: TestClient) -> None:
    ctx = _seed(api)
    resp = create_order(api, ctx["reg"].access, 999999, [{"product_id": ctx["pid"], "quantity": 1}])
    assert resp.status_code == 404


def test_create_order_unknown_product_422(api: TestClient) -> None:
    ctx = _seed(api)
    resp = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": 999999, "quantity": 1}]
    )
    assert resp.status_code == 422


def test_soft_deleted_product_rejected_for_new_order(api: TestClient) -> None:
    ctx = _seed(api)
    set_pin(api, ctx["reg"].access, "4321")
    api.delete(
        f"/api/products/{ctx['pid']}",
        headers={**auth_header(ctx["reg"].access), "X-Business-PIN": "4321"},
    )
    resp = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 1}]
    )
    assert resp.status_code == 422


# --- lifecycle & inventory --------------------------------------------------


def test_confirm_decrements_inventory(api: TestClient, captured_order_events: list) -> None:
    ctx = _seed(api, qty=10)
    order = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 7}]
    ).json()
    resp = transition_order(api, ctx["reg"].access, order["id"], "CONFIRM")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CONFIRMED"
    assert _stock(api, ctx["reg"].access, ctx["inv_id"]) == 3
    assert any(isinstance(e, OrderConfirmed) for e in captured_order_events)


def test_confirm_insufficient_stock_keeps_order_created(api: TestClient) -> None:
    ctx = _seed(api, qty=5)
    order = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 9}]
    ).json()
    resp = transition_order(api, ctx["reg"].access, order["id"], "CONFIRM")
    assert resp.status_code == 409
    # Atomic: order stays CREATED and stock is untouched.
    assert (
        api.get(f"/api/orders/{order['id']}", headers=auth_header(ctx["reg"].access)).json()[
            "status"
        ]
        == "CREATED"
    )
    assert _stock(api, ctx["reg"].access, ctx["inv_id"]) == 5


def test_cancel_confirmed_restores_inventory(api: TestClient, captured_order_events: list) -> None:
    ctx = _seed(api, qty=10)
    order = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 4}]
    ).json()
    transition_order(api, ctx["reg"].access, order["id"], "CONFIRM")
    assert _stock(api, ctx["reg"].access, ctx["inv_id"]) == 6
    resp = transition_order(api, ctx["reg"].access, order["id"], "CANCEL")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"
    assert _stock(api, ctx["reg"].access, ctx["inv_id"]) == 10  # restored
    assert any(isinstance(e, OrderCancelled) for e in captured_order_events)


def test_double_cancel_does_not_double_restore(api: TestClient) -> None:
    ctx = _seed(api, qty=10)
    order = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 4}]
    ).json()
    transition_order(api, ctx["reg"].access, order["id"], "CONFIRM")
    transition_order(api, ctx["reg"].access, order["id"], "CANCEL")
    second = transition_order(api, ctx["reg"].access, order["id"], "CANCEL")
    assert second.status_code == 409  # terminal; rejected
    assert _stock(api, ctx["reg"].access, ctx["inv_id"]) == 10  # not restored twice


def test_cancel_created_order_no_inventory_change(api: TestClient) -> None:
    ctx = _seed(api, qty=10)
    order = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 4}]
    ).json()
    resp = transition_order(api, ctx["reg"].access, order["id"], "CANCEL")
    assert resp.status_code == 200
    assert _stock(api, ctx["reg"].access, ctx["inv_id"]) == 10


def test_full_lifecycle_happy_path(api: TestClient) -> None:
    # PAID is reached via the payment flow, not a client PAY transition.
    ctx = _seed(api, qty=10)
    order = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 2}]
    ).json()
    assert transition_order(api, ctx["reg"].access, order["id"], "CONFIRM").json()["status"] == (
        "CONFIRMED"
    )
    # Client PAY transition is now blocked (must use the payment API).
    assert transition_order(api, ctx["reg"].access, order["id"], "PAY").status_code == 409
    payment = pay_order_online(api, ctx["reg"].access, order["id"])
    assert payment["status"] == "SUCCESS"
    assert (
        api.get(f"/api/orders/{order['id']}", headers=auth_header(ctx["reg"].access)).json()[
            "status"
        ]
        == "PAID"
    )
    for event, expected in [
        ("PACK", "PACKED"),
        ("SHIP", "SHIPPED"),
        ("DELIVER", "DELIVERED"),
        ("CLOSE", "COMPLETED"),
    ]:
        resp = transition_order(api, ctx["reg"].access, order["id"], event)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == expected


def test_illegal_transition_rejected(api: TestClient) -> None:
    ctx = _seed(api, qty=10)
    order = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 2}]
    ).json()
    resp = transition_order(api, ctx["reg"].access, order["id"], "SHIP")  # from CREATED
    assert resp.status_code == 409


def test_order_history_survives_price_change(api: TestClient) -> None:
    ctx = _seed(api, price="40.00")
    order = create_order(
        api, ctx["reg"].access, ctx["cust"], [{"product_id": ctx["pid"], "quantity": 2}]
    ).json()
    # Change the catalog price after the order exists.
    api.patch(
        f"/api/products/{ctx['pid']}",
        headers=auth_header(ctx["reg"].access),
        json={"price": "99.00"},
    )
    fetched = api.get(f"/api/orders/{order['id']}", headers=auth_header(ctx["reg"].access)).json()
    assert fetched["items"][0]["unit_price"] == "40.00"  # snapshot unchanged
    assert fetched["total"] == "80.00"
