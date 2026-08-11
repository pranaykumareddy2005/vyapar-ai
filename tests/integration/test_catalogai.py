"""Integration tests: AI catalog draft lifecycle end to end (Phase 4).

Uses the deterministic MockAiProvider (the test default). Provider-failure cases
override the AI provider dependency with a failing stub.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from app.catalogai.provider import (
    AiInvalidResponse,
    AiProvider,
    AiProviderTimeout,
    AiProviderUnavailable,
)
from app.db import get_session
from app.main import create_app
from app.providers import get_ai_provider
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.helpers import (
    auth_header,
    create_category,
    generate_draft,
    register_business,
)


class _FailingProvider:
    name = "mock"
    model = "mock-1"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def describe(self, image: bytes, content_type: str) -> object:
        raise self._exc


@pytest.fixture
def make_api(db_session: Session) -> Iterator[Callable[..., TestClient]]:
    created: list[tuple[object, TestClient]] = []

    def _make(provider: AiProvider | None = None) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_session] = lambda: db_session
        if provider is not None:
            app.dependency_overrides[get_ai_provider] = lambda: provider
        client = TestClient(app)
        created.append((app, client))
        return client

    yield _make
    for app, _client in created:
        app.dependency_overrides.clear()  # type: ignore[attr-defined]


# --- generation & review ----------------------------------------------------


def test_generate_returns_draft_without_price(api: TestClient) -> None:
    reg = register_business(api)
    resp = generate_draft(api, reg.access)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "GENERATED"
    assert body["name"] == "Sample Product"
    assert body["price"] is None  # never inferred from an image
    assert body["source_image_url"]
    assert body["ai_provider"] == "mock"


def test_generation_does_not_create_a_product(api: TestClient) -> None:
    """CRITICAL: an AI draft must NOT create a Product before approval."""
    reg = register_business(api)
    generate_draft(api, reg.access)
    products = api.get("/api/products", headers=auth_header(reg.access)).json()
    assert products == []


def test_retrieve_and_list_draft(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    got = api.get(f"/api/catalog-ai/drafts/{draft_id}", headers=auth_header(reg.access))
    assert got.status_code == 200
    listing = api.get("/api/catalog-ai/drafts", headers=auth_header(reg.access)).json()
    assert [d["id"] for d in listing] == [draft_id]


def test_low_confidence_is_flagged(make_api: Callable[..., TestClient]) -> None:
    from app.catalogai.provider import MockAiProvider

    api = make_api(MockAiProvider(confidence=0.2))
    reg = register_business(api)
    body = generate_draft(api, reg.access).json()
    assert body["confidence"] == 0.2
    assert body["low_confidence"] is True


# --- category matching ------------------------------------------------------


def test_suggested_category_matches_existing(api: TestClient) -> None:
    reg = register_business(api)
    cat = create_category(api, reg.access, "Groceries")  # mock suggests "Groceries"
    body = generate_draft(api, reg.access).json()
    assert body["category_suggestion"] == "Groceries"
    assert body["category_id"] == cat["id"]


def test_unmatched_category_is_not_auto_created(api: TestClient) -> None:
    reg = register_business(api)
    body = generate_draft(api, reg.access).json()
    assert body["category_id"] is None  # no matching category exists
    assert api.get("/api/categories", headers=auth_header(reg.access)).json() == []


def test_edit_rejects_unowned_category(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    resp = api.patch(
        f"/api/catalog-ai/drafts/{draft_id}",
        headers=auth_header(reg.access),
        json={"category_id": 999999},
    )
    assert resp.status_code == 422


# --- approval ---------------------------------------------------------------


def test_approve_requires_price(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    resp = api.post(f"/api/catalog-ai/drafts/{draft_id}/approve", headers=auth_header(reg.access))
    assert resp.status_code == 422
    assert "price" in resp.json()["error"]["message"]


def test_full_approve_creates_product_via_catalog(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    # Merchant edits: confirm SKU and provide the price (only trusted source).
    api.patch(
        f"/api/catalog-ai/drafts/{draft_id}",
        headers=auth_header(reg.access),
        json={"sku": "TEA-1", "price": "120.00"},
    )
    resp = api.post(f"/api/catalog-ai/drafts/{draft_id}/approve", headers=auth_header(reg.access))
    assert resp.status_code == 201, resp.text
    product = resp.json()
    assert product["sku"] == "TEA-1"
    assert product["price"] == "120.00"
    # The product now exists in the catalog.
    products = api.get("/api/products", headers=auth_header(reg.access)).json()
    assert [p["id"] for p in products] == [product["id"]]
    # The draft is now APPROVED and linked to the product.
    draft = api.get(f"/api/catalog-ai/drafts/{draft_id}", headers=auth_header(reg.access)).json()
    assert draft["status"] == "APPROVED"
    assert draft["approved_product_id"] == product["id"]
    assert draft["approved_by"] == reg.user_id


def test_approve_can_supply_price_inline(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    resp = api.post(
        f"/api/catalog-ai/drafts/{draft_id}/approve",
        headers=auth_header(reg.access),
        json={"sku": "INLINE-1", "price": "9.50"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["price"] == "9.50"


def test_duplicate_approval_is_idempotent(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    api.patch(
        f"/api/catalog-ai/drafts/{draft_id}",
        headers=auth_header(reg.access),
        json={"sku": "DUP-1", "price": "10.00"},
    )
    first = api.post(
        f"/api/catalog-ai/drafts/{draft_id}/approve", headers=auth_header(reg.access)
    ).json()
    second = api.post(
        f"/api/catalog-ai/drafts/{draft_id}/approve", headers=auth_header(reg.access)
    ).json()
    assert first["id"] == second["id"]  # same product, no duplicate
    products = api.get("/api/products", headers=auth_header(reg.access)).json()
    assert len(products) == 1


# --- rejection & regeneration ----------------------------------------------


def test_reject_then_approve_conflicts(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    rej = api.post(f"/api/catalog-ai/drafts/{draft_id}/reject", headers=auth_header(reg.access))
    assert rej.status_code == 200
    assert rej.json()["status"] == "REJECTED"
    approve = api.post(
        f"/api/catalog-ai/drafts/{draft_id}/approve",
        headers=auth_header(reg.access),
        json={"sku": "X", "price": "1.00"},
    )
    assert approve.status_code == 409


def test_regenerate_reuses_source_image(api: TestClient) -> None:
    reg = register_business(api)
    draft_id = generate_draft(api, reg.access).json()["id"]
    resp = api.post(
        f"/api/catalog-ai/drafts/{draft_id}/regenerate", headers=auth_header(reg.access)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "GENERATED"


# --- idempotent generation --------------------------------------------------


def test_request_key_makes_generation_idempotent(api: TestClient) -> None:
    reg = register_business(api)
    first = generate_draft(api, reg.access, request_key="k-1").json()
    second = generate_draft(api, reg.access, request_key="k-1").json()
    assert first["id"] == second["id"]


# --- provider failure -------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        AiProviderTimeout("timeout"),
        AiProviderUnavailable("unavailable"),
        AiInvalidResponse("garbage"),
    ],
)
def test_provider_failure_persists_failed_draft(
    make_api: Callable[..., TestClient], exc: Exception
) -> None:
    api = make_api(_FailingProvider(exc))
    reg = register_business(api)
    resp = generate_draft(api, reg.access)
    assert resp.status_code == 502  # fail loudly, never a silent success
    # The failure is recorded durably in a retryable FAILED draft.
    drafts = api.get("/api/catalog-ai/drafts", headers=auth_header(reg.access)).json()
    assert len(drafts) == 1
    assert drafts[0]["status"] == "FAILED"
    assert drafts[0]["error_code"] == exc.code  # type: ignore[attr-defined]
    # No product was created.
    assert api.get("/api/products", headers=auth_header(reg.access)).json() == []


def test_non_image_upload_is_rejected(api: TestClient) -> None:
    reg = register_business(api)
    resp = generate_draft(api, reg.access, content=b"pdf", content_type="application/pdf")
    assert resp.status_code == 422
