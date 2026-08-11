"""Integration tests: inventory lifecycle, movements, thresholds, low-stock event."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.common.events import LowStock, event_bus
from fastapi.testclient import TestClient

from tests.integration.helpers import (
    adjust_stock,
    auth_header,
    create_inventory,
    create_product,
    register_business,
)


@pytest.fixture
def captured_low_stock() -> Iterator[list[LowStock]]:
    """Capture LowStock events published on the in-process bus during a test."""
    events: list[LowStock] = []
    event_bus.subscribe(LowStock, events.append)
    try:
        yield events
    finally:
        event_bus.clear()


def _product(api: TestClient, access: str, sku: str = "INV-1") -> int:
    return create_product(api, access, sku=sku)["id"]


# --- creation & retrieval ---------------------------------------------------


def test_create_and_get_inventory(api: TestClient) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    resp = create_inventory(api, reg.access, pid, quantity=10, low_stock_threshold=3)
    assert resp.status_code == 201, resp.text
    inv = resp.json()
    assert inv["quantity"] == 10
    assert inv["low_stock"] is False
    got = api.get(f"/api/inventory/{inv['id']}", headers=auth_header(reg.access))
    assert got.status_code == 200
    assert got.json()["product_id"] == pid


def test_duplicate_inventory_rejected(api: TestClient) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    assert create_inventory(api, reg.access, pid).status_code == 201
    assert create_inventory(api, reg.access, pid).status_code == 409


def test_inventory_for_missing_product_is_404(api: TestClient) -> None:
    reg = register_business(api)
    resp = create_inventory(api, reg.access, 999999)
    assert resp.status_code == 404


def test_list_inventory_is_tenant_scoped(api: TestClient) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    create_inventory(api, reg.access, pid, quantity=5)
    listing = api.get("/api/inventory", headers=auth_header(reg.access)).json()
    assert len(listing) == 1
    assert listing[0]["product_id"] == pid


# --- adjustments & movements ------------------------------------------------


def test_restock_and_sale_adjustments(api: TestClient) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    inv_id = create_inventory(api, reg.access, pid, quantity=0).json()["id"]

    r1 = adjust_stock(api, reg.access, inv_id, delta=20, movement_type="RESTOCK")
    assert r1.status_code == 200
    assert r1.json()["quantity"] == 20

    r2 = adjust_stock(api, reg.access, inv_id, delta=-5, movement_type="SALE")
    assert r2.json()["quantity"] == 15

    movements = api.get(
        f"/api/inventory/{inv_id}/movements", headers=auth_header(reg.access)
    ).json()
    assert [(m["delta"], m["resulting_quantity"], m["movement_type"]) for m in movements] == [
        (20, 20, "RESTOCK"),
        (-5, 15, "SALE"),
    ]


def test_zero_delta_rejected(api: TestClient) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    inv_id = create_inventory(api, reg.access, pid, quantity=5).json()["id"]
    resp = adjust_stock(api, reg.access, inv_id, delta=0)
    assert resp.status_code == 422


def test_negative_stock_rejected_without_movement(api: TestClient) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    inv_id = create_inventory(api, reg.access, pid, quantity=3).json()["id"]
    resp = adjust_stock(api, reg.access, inv_id, delta=-5, movement_type="SALE")
    assert resp.status_code == 409  # InsufficientStockError
    # Quantity unchanged and no movement recorded for the rejected attempt.
    assert (
        api.get(f"/api/inventory/{inv_id}", headers=auth_header(reg.access)).json()["quantity"] == 3
    )
    movements = api.get(
        f"/api/inventory/{inv_id}/movements", headers=auth_header(reg.access)
    ).json()
    assert movements == []


def test_adjust_missing_inventory_is_404(api: TestClient) -> None:
    reg = register_business(api)
    resp = adjust_stock(api, reg.access, 999999, delta=1)
    assert resp.status_code == 404


# --- thresholds & low-stock event -------------------------------------------


def test_update_threshold(api: TestClient) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    inv_id = create_inventory(api, reg.access, pid, quantity=10, low_stock_threshold=1).json()["id"]
    resp = api.patch(
        f"/api/inventory/{inv_id}",
        headers=auth_header(reg.access),
        json={"low_stock_threshold": 5},
    )
    assert resp.status_code == 200
    assert resp.json()["low_stock_threshold"] == 5


def test_low_stock_event_published_on_crossing_threshold(
    api: TestClient, captured_low_stock: list[LowStock]
) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    inv_id = create_inventory(api, reg.access, pid, quantity=10, low_stock_threshold=5).json()["id"]

    # Drop to exactly the threshold (5 <= 5) -> low-stock event.
    resp = adjust_stock(api, reg.access, inv_id, delta=-5, movement_type="SALE")
    assert resp.json()["low_stock"] is True
    assert len(captured_low_stock) == 1
    event = captured_low_stock[0]
    assert event.business_id == reg.business_id
    assert event.product_id == pid
    assert event.quantity == 5
    assert event.threshold == 5


def test_no_low_stock_event_above_threshold(
    api: TestClient, captured_low_stock: list[LowStock]
) -> None:
    reg = register_business(api)
    pid = _product(api, reg.access)
    inv_id = create_inventory(api, reg.access, pid, quantity=10, low_stock_threshold=2).json()["id"]
    adjust_stock(api, reg.access, inv_id, delta=-3, movement_type="SALE")  # 7 > 2
    assert captured_low_stock == []


# --- future-integration entry point (OrderService / Conversation, §25/§26) --


def test_adjust_stock_by_product_entry_point(api: TestClient, db_session: object) -> None:
    """The product-keyed method a future OrderService/handler will call, routed
    through the same authoritative adjust_stock."""
    import pytest as _pytest
    from app.catalog.repository import ProductRepository
    from app.common.events import EventBus
    from app.common.exceptions import NotFoundError
    from app.inventory.models import MovementType
    from app.inventory.repository import InventoryRepository, StockMovementRepository
    from app.inventory.service import InventoryService
    from sqlalchemy.orm import Session

    reg = register_business(api)
    pid = _product(api, reg.access)
    create_inventory(api, reg.access, pid, quantity=4)

    assert isinstance(db_session, Session)
    service = InventoryService(
        db_session,
        InventoryRepository(db_session),
        StockMovementRepository(db_session),
        ProductRepository(db_session),
        events=EventBus(),
    )
    inventory = service.adjust_stock_by_product(
        reg.business_id, pid, delta=10, movement_type=MovementType.RESTOCK
    )
    assert inventory.quantity == 14

    with _pytest.raises(NotFoundError):
        service.get_inventory_by_product(reg.business_id, 999999)
