"""Integration tests: full conversation pipeline over Catalog + Inventory.

Uses the deterministic MockConversationAiProvider (test default). Verifies that
supported intents drive the real domain services, unsupported intents are handled
safely, and no mutation occurs unless every stage succeeds.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from app.conversation.provider import ConversationAiUnavailable
from app.db import get_session
from app.main import create_app
from app.providers import get_conversation_ai_provider
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.helpers import (
    auth_header,
    converse,
    create_inventory,
    create_product,
    register_business,
)


class _FailingProvider:
    name = "mock"
    model = "mock-conv-1"

    def resolve(self, text: str) -> object:
        raise ConversationAiUnavailable("down")


@pytest.fixture
def make_api(db_session: Session) -> Iterator[Callable[..., TestClient]]:
    created: list[tuple[object, TestClient]] = []

    def _make(provider: object | None = None) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_session] = lambda: db_session
        if provider is not None:
            app.dependency_overrides[get_conversation_ai_provider] = lambda: provider
        client = TestClient(app)
        created.append((app, client))
        return client

    yield _make
    for app, _client in created:
        app.dependency_overrides.clear()  # type: ignore[attr-defined]


def _seed(api: TestClient, *, name: str = "Notebook", sku: str = "NB-1", qty: int = 10) -> dict:
    reg = register_business(api)
    pid = create_product(api, reg.access, name=name, sku=sku)["id"]
    create_inventory(api, reg.access, pid, quantity=qty, low_stock_threshold=2)
    return {"reg": reg, "pid": pid}


def _stock(api: TestClient, access: str, pid: int) -> int:
    inv = api.get("/api/inventory", headers=auth_header(access)).json()
    return next(i["quantity"] for i in inv if i["product_id"] == pid)


# --- supported intents ------------------------------------------------------


def test_search_returns_real_products(api: TestClient) -> None:
    ctx = _seed(api)
    resp = converse(api, ctx["reg"].access, "show me notebooks")
    body = resp.json()
    assert body["intent"] == "SEARCH_PRODUCT"
    assert body["outcome"] == "EXECUTED"
    assert "Notebook" in body["reply"]


def test_get_stock_returns_real_quantity(api: TestClient) -> None:
    ctx = _seed(api, qty=10)
    body = converse(api, ctx["reg"].access, "how many notebooks are left?").json()
    assert body["intent"] == "GET_STOCK"
    assert body["outcome"] == "EXECUTED"
    assert "10 units" in body["reply"]


def test_adjust_add_mutates_and_records_movement(api: TestClient) -> None:
    ctx = _seed(api, qty=10)
    body = converse(api, ctx["reg"].access, "add 20 notebooks").json()
    assert body["outcome"] == "EXECUTED"
    assert "Current stock: 30" in body["reply"]
    assert _stock(api, ctx["reg"].access, ctx["pid"]) == 30
    # A StockMovement was recorded through InventoryService.
    inv = api.get("/api/inventory", headers=auth_header(ctx["reg"].access)).json()[0]
    movements = api.get(
        f"/api/inventory/{inv['id']}/movements", headers=auth_header(ctx["reg"].access)
    ).json()
    assert movements[-1]["delta"] == 20


def test_adjust_remove_damage(api: TestClient) -> None:
    ctx = _seed(api, qty=10)
    body = converse(api, ctx["reg"].access, "remove 4 damaged notebooks").json()
    assert body["outcome"] == "EXECUTED"
    assert _stock(api, ctx["reg"].access, ctx["pid"]) == 6


# --- safe non-execution paths (no mutation) ---------------------------------


def test_insufficient_stock_is_rejected(api: TestClient) -> None:
    ctx = _seed(api, qty=5)
    body = converse(api, ctx["reg"].access, "remove 1000 notebooks").json()
    assert body["outcome"] == "REJECTED"
    assert _stock(api, ctx["reg"].access, ctx["pid"]) == 5  # unchanged


def test_ambiguous_asks_clarification(api: TestClient) -> None:
    ctx = _seed(api)
    body = converse(api, ctx["reg"].access, "do something with notebooks").json()
    assert body["outcome"] == "CLARIFICATION"
    assert _stock(api, ctx["reg"].access, ctx["pid"]) == 10


def test_missing_quantity_asks_clarification(api: TestClient) -> None:
    ctx = _seed(api)
    body = converse(api, ctx["reg"].access, "add notebooks").json()
    assert body["outcome"] == "CLARIFICATION"
    assert "How many" in body["reply"]
    assert _stock(api, ctx["reg"].access, ctx["pid"]) == 10


def test_missing_product_asks_clarification(api: TestClient) -> None:
    ctx = _seed(api)
    body = converse(api, ctx["reg"].access, "add 20").json()
    assert body["outcome"] == "CLARIFICATION"
    assert _stock(api, ctx["reg"].access, ctx["pid"]) == 10


def test_low_confidence_does_not_execute(api: TestClient) -> None:
    ctx = _seed(api)
    body = converse(api, ctx["reg"].access, "add some notebooks").json()
    assert body["outcome"] == "CLARIFICATION"
    assert _stock(api, ctx["reg"].access, ctx["pid"]) == 10


def test_product_not_found(api: TestClient) -> None:
    reg = register_business(api)
    body = converse(api, reg.access, "how many staplers are left?").json()
    assert body["outcome"] == "NOT_FOUND"


def test_multiple_matches_ask_clarification(api: TestClient) -> None:
    reg = register_business(api)
    for i, sku in enumerate(("NB-A", "NB-B")):
        pid = create_product(api, reg.access, name=f"Notebook {i}", sku=sku)["id"]
        create_inventory(api, reg.access, pid, quantity=5)
    body = converse(api, reg.access, "add 5 notebooks").json()
    assert body["outcome"] == "CLARIFICATION"
    assert "multiple" in body["reply"].lower()


def test_unsupported_order_not_fabricated(api: TestClient) -> None:
    reg = register_business(api)
    body = converse(api, reg.access, "create an order for 5 notebooks").json()
    assert body["intent"] == "UNSUPPORTED"
    assert body["outcome"] == "UNSUPPORTED"


# --- provider failure -------------------------------------------------------


def test_provider_failure_is_controlled(make_api: Callable[..., TestClient]) -> None:
    api = make_api(_FailingProvider())
    reg = register_business(api)
    body = converse(api, reg.access, "add 20 notebooks").json()
    assert body["outcome"] == "ERROR"
    assert "went wrong" in body["reply"] or "couldn't process" in body["reply"]


# --- dev simulation E2E -----------------------------------------------------


def test_dev_simulate_conversation_pipeline(api: TestClient) -> None:
    ctx = _seed(api, qty=10)
    resp = api.post(
        "/dev/simulate-conversation",
        json={
            "business_id": ctx["reg"].business_id,
            "sender_phone": "+9199",
            "text": "add 20 notebooks",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "EXECUTED"
    assert body["provider_message_id"].startswith("mock-")
