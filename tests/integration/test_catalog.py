"""Catalog integration tests: CRUD, filtering, soft delete, images, constraints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_product,
    register_business,
    set_pin,
)


def _category(api: TestClient, access: str, name: str = "Stationery") -> int:
    resp = api.post("/api/categories", headers=auth_header(access), json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- categories -------------------------------------------------------------


def test_create_and_list_category(api: TestClient) -> None:
    reg = register_business(api)
    cid = _category(api, reg.access, "Drinks")
    resp = api.get("/api/categories", headers=auth_header(reg.access))
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert "Drinks" in names
    assert isinstance(cid, int)


def test_duplicate_category_name_conflict(api: TestClient) -> None:
    reg = register_business(api)
    _category(api, reg.access, "Drinks")
    resp = api.post("/api/categories", headers=auth_header(reg.access), json={"name": "Drinks"})
    assert resp.status_code == 409


# --- products ---------------------------------------------------------------


def test_create_and_get_product(api: TestClient) -> None:
    reg = register_business(api)
    cid = _category(api, reg.access)
    body = create_product(api, reg.access, sku="P-1", category_id=cid, price="99.99")
    assert body["price"] == "99.99"
    assert body["category_id"] == cid
    got = api.get(f"/api/products/{body['id']}", headers=auth_header(reg.access))
    assert got.status_code == 200
    assert got.json()["sku"] == "P-1"


def test_update_product(api: TestClient) -> None:
    reg = register_business(api)
    body = create_product(api, reg.access, sku="P-2")
    resp = api.patch(
        f"/api/products/{body['id']}",
        headers=auth_header(reg.access),
        json={"name": "Renamed", "price": "12.00"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["price"] == "12.00"


def test_duplicate_sku_conflict(api: TestClient) -> None:
    reg = register_business(api)
    create_product(api, reg.access, sku="DUP")
    resp = api.post(
        "/api/products",
        headers=auth_header(reg.access),
        json={"name": "Other", "price": "5.00", "sku": "DUP"},
    )
    assert resp.status_code == 409


def test_product_with_foreign_business_category_rejected(api: TestClient) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_cat = _category(api, b.access, "B-Cat")
    # A attempts to create a product referencing B's category id.
    resp = api.post(
        "/api/products",
        headers=auth_header(a.access),
        json={"name": "X", "price": "1.00", "sku": "AX", "category_id": b_cat},
    )
    assert resp.status_code == 422  # ValidationError -> category not for this business


def test_nonexistent_category_rejected(api: TestClient) -> None:
    reg = register_business(api)
    resp = api.post(
        "/api/products",
        headers=auth_header(reg.access),
        json={"name": "X", "price": "1.00", "sku": "AX", "category_id": 999999},
    )
    assert resp.status_code == 422


def test_get_nonexistent_product_404(api: TestClient) -> None:
    reg = register_business(api)
    resp = api.get("/api/products/999999", headers=auth_header(reg.access))
    assert resp.status_code == 404


# --- soft delete ------------------------------------------------------------


def test_soft_delete_hides_from_listing(api: TestClient) -> None:
    reg = register_business(api)
    set_pin(api, reg.access, "4321")
    body = create_product(api, reg.access, sku="DEL-1")
    pid = body["id"]
    delete = api.delete(
        f"/api/products/{pid}",
        headers={**auth_header(reg.access), "X-Business-PIN": "4321"},
    )
    assert delete.status_code == 204
    # Normal listing and retrieval exclude the deleted product.
    listing = api.get("/api/products", headers=auth_header(reg.access))
    assert all(p["id"] != pid for p in listing.json())
    assert api.get(f"/api/products/{pid}", headers=auth_header(reg.access)).status_code == 404


def test_sku_reusable_after_soft_delete(api: TestClient) -> None:
    reg = register_business(api)
    set_pin(api, reg.access, "4321")
    first = create_product(api, reg.access, sku="REUSE")
    api.delete(
        f"/api/products/{first['id']}",
        headers={**auth_header(reg.access), "X-Business-PIN": "4321"},
    )
    # A new active product may reclaim the deleted product's SKU.
    second = create_product(api, reg.access, sku="REUSE", name="New")
    assert second["id"] != first["id"]


def test_delete_requires_pin(api: TestClient) -> None:
    reg = register_business(api)
    set_pin(api, reg.access, "4321")
    body = create_product(api, reg.access, sku="NOPIN")
    resp = api.delete(f"/api/products/{body['id']}", headers=auth_header(reg.access))
    assert resp.status_code == 403


# --- filtering --------------------------------------------------------------


def test_keyword_and_category_filtering(api: TestClient) -> None:
    reg = register_business(api)
    drinks = _category(api, reg.access, "Drinks")
    snacks = _category(api, reg.access, "Snacks")
    create_product(api, reg.access, name="Cola Bottle", sku="C1", category_id=drinks)
    create_product(api, reg.access, name="Cola Can", sku="C2", category_id=drinks)
    create_product(api, reg.access, name="Chips", sku="S1", category_id=snacks)

    kw = api.get("/api/products", headers=auth_header(reg.access), params={"q": "cola"})
    assert {p["sku"] for p in kw.json()} == {"C1", "C2"}

    cat = api.get("/api/products", headers=auth_header(reg.access), params={"category_id": snacks})
    assert {p["sku"] for p in cat.json()} == {"S1"}

    combo = api.get(
        "/api/products",
        headers=auth_header(reg.access),
        params={"q": "cola", "category_id": snacks},
    )
    assert combo.json() == []

    empty = api.get("/api/products", headers=auth_header(reg.access), params={"q": ""})
    assert len(empty.json()) == 3  # empty keyword -> no keyword filter


# --- images -----------------------------------------------------------------


def test_upload_and_list_product_image(api: TestClient) -> None:
    reg = register_business(api)
    body = create_product(api, reg.access, sku="IMG-1")
    pid = body["id"]
    up = api.post(
        f"/api/products/{pid}/images",
        headers=auth_header(reg.access),
        files={"file": ("photo.jpg", b"\xff\xd8\xff-bytes", "image/jpeg")},
        data={"is_primary": "true"},
    )
    assert up.status_code == 201, up.text
    meta = up.json()
    assert meta["content_type"] == "image/jpeg"
    assert meta["is_primary"] is True
    assert "storage_key" not in meta  # internal field not exposed

    listing = api.get(f"/api/products/{pid}/images", headers=auth_header(reg.access))
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_reject_non_image_upload(api: TestClient) -> None:
    reg = register_business(api)
    body = create_product(api, reg.access, sku="IMG-2")
    resp = api.post(
        f"/api/products/{body['id']}/images",
        headers=auth_header(reg.access),
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 422
