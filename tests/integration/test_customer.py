"""Integration tests: customer lifecycle, uniqueness, soft delete, addresses."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_customer,
    register_business,
)


def test_create_get_list_customer(api: TestClient) -> None:
    reg = register_business(api)
    cust = create_customer(api, reg.access, name="Asha", phone="+919111111111")
    got = api.get(f"/api/customers/{cust['id']}", headers=auth_header(reg.access))
    assert got.status_code == 200
    assert got.json()["name"] == "Asha"
    listing = api.get("/api/customers", headers=auth_header(reg.access)).json()
    assert [c["id"] for c in listing] == [cust["id"]]


def test_duplicate_active_phone_rejected(api: TestClient) -> None:
    reg = register_business(api)
    create_customer(api, reg.access, phone="+919111111111")
    dup = api.post(
        "/api/customers",
        headers=auth_header(reg.access),
        json={"name": "Other", "phone": "+919111111111"},
    )
    assert dup.status_code == 409


def test_update_customer(api: TestClient) -> None:
    reg = register_business(api)
    cust = create_customer(api, reg.access)
    resp = api.patch(
        f"/api/customers/{cust['id']}",
        headers=auth_header(reg.access),
        json={"name": "Renamed"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


def test_update_to_duplicate_phone_rejected(api: TestClient) -> None:
    reg = register_business(api)
    create_customer(api, reg.access, name="A", phone="+919111111111")
    b = create_customer(api, reg.access, name="B", phone="+919222222222")
    resp = api.patch(
        f"/api/customers/{b['id']}",
        headers=auth_header(reg.access),
        json={"phone": "+919111111111"},
    )
    assert resp.status_code == 409


def test_soft_delete_excludes_from_list_and_frees_phone(api: TestClient) -> None:
    reg = register_business(api)
    cust = create_customer(api, reg.access, phone="+919111111111")
    assert (
        api.delete(f"/api/customers/{cust['id']}", headers=auth_header(reg.access)).status_code
        == 204
    )
    assert api.get("/api/customers", headers=auth_header(reg.access)).json() == []
    # Phone can be reused after soft delete.
    again = api.post(
        "/api/customers",
        headers=auth_header(reg.access),
        json={"name": "New", "phone": "+919111111111"},
    )
    assert again.status_code == 201


def test_addresses(api: TestClient) -> None:
    reg = register_business(api)
    cust = create_customer(api, reg.access)
    resp = api.post(
        f"/api/customers/{cust['id']}/addresses",
        headers=auth_header(reg.access),
        json={"line": "1 Market Rd", "city": "Pune", "pin": "411001"},
    )
    assert resp.status_code == 201
    addrs = api.get(
        f"/api/customers/{cust['id']}/addresses", headers=auth_header(reg.access)
    ).json()
    assert [a["city"] for a in addrs] == ["Pune"]
