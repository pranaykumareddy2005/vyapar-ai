"""Integration tests: invoice generation, PDF, numbering, historical correctness."""

from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.integration.helpers import (
    auth_header,
    create_customer,
    create_inventory,
    create_order,
    create_product,
    generate_invoice,
    pay_order_online,
    register_business,
    transition_order,
)


def _paid_order(
    api: TestClient, reg: object, *, sku: str, price: str = "40.00", qty: int = 3
) -> dict:
    pid = create_product(api, reg.access, name="Notebook", sku=sku, price=price)["id"]  # type: ignore[attr-defined]
    create_inventory(api, reg.access, pid, quantity=10)  # type: ignore[attr-defined]
    cust = create_customer(api, reg.access, phone=f"+9199{sku}")["id"]  # type: ignore[attr-defined]
    order = create_order(api, reg.access, cust, [{"product_id": pid, "quantity": qty}]).json()  # type: ignore[attr-defined]
    transition_order(api, reg.access, order["id"], "CONFIRM")  # type: ignore[attr-defined]
    # Unique provider payment id per order (Phase-8 replay protection).
    pay_order_online(api, reg.access, order["id"], pid=f"pay_ok_{sku}")  # type: ignore[attr-defined]
    return {"order": order["id"], "pid": pid, "cust": cust}


# --- generation & eligibility -----------------------------------------------


def test_generate_invoice_from_paid_order(api: TestClient) -> None:
    reg = register_business(api)
    ctx = _paid_order(api, reg, sku="NB-1", price="40.00", qty=3)
    resp = generate_invoice(api, reg.access, ctx["order"])
    assert resp.status_code == 201, resp.text
    inv = resp.json()
    assert inv["invoice_number"].startswith("INV-")
    assert inv["invoice_number"].endswith("-0001")
    assert inv["subtotal"] == "120.00"
    assert inv["tax"] == "0.00"
    assert inv["total"] == "120.00"
    assert inv["status"] == "ISSUED"
    assert inv["payment_status"] == "PAID"
    assert inv["payment_method"] == "ONLINE"
    assert inv["items"][0]["product_name"] == "Notebook"
    assert inv["items"][0]["unit_price"] == "40.00"
    assert inv["pdf_available"] is True


def test_generate_is_idempotent(api: TestClient) -> None:
    reg = register_business(api)
    ctx = _paid_order(api, reg, sku="NB-2")
    a = generate_invoice(api, reg.access, ctx["order"]).json()
    b = generate_invoice(api, reg.access, ctx["order"]).json()
    assert a["id"] == b["id"]
    assert a["invoice_number"] == b["invoice_number"]
    assert len(api.get("/api/invoices", headers=auth_header(reg.access)).json()) == 1


def test_invoice_rejected_for_unpaid_order(api: TestClient) -> None:
    reg = register_business(api)
    pid = create_product(api, reg.access, sku="NB-U")["id"]
    create_inventory(api, reg.access, pid, quantity=10)
    cust = create_customer(api, reg.access)["id"]
    order = create_order(api, reg.access, cust, [{"product_id": pid, "quantity": 1}]).json()
    # CREATED -> not eligible.
    assert generate_invoice(api, reg.access, order["id"]).status_code == 409
    # CONFIRMED but not paid -> still not eligible.
    transition_order(api, reg.access, order["id"], "CONFIRM")
    assert generate_invoice(api, reg.access, order["id"]).status_code == 409


def test_sequential_numbering_per_business(api: TestClient) -> None:
    reg = register_business(api)
    c1 = _paid_order(api, reg, sku="NB-A")
    c2 = _paid_order(api, reg, sku="NB-B")
    n1 = generate_invoice(api, reg.access, c1["order"]).json()["invoice_number"]
    n2 = generate_invoice(api, reg.access, c2["order"]).json()["invoice_number"]
    assert n1.endswith("-0001")
    assert n2.endswith("-0002")


# --- PDF --------------------------------------------------------------------


def test_pdf_download_contains_invoice(api: TestClient) -> None:
    reg = register_business(api)
    ctx = _paid_order(api, reg, sku="NB-P")
    inv = generate_invoice(api, reg.access, ctx["order"]).json()
    resp = api.get(f"/api/invoices/{inv['id']}/pdf", headers=auth_header(reg.access))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    text = "".join(p.extract_text() or "" for p in PdfReader(BytesIO(resp.content)).pages)
    assert inv["invoice_number"] in text
    assert "Notebook" in text
    assert "120.00" in text


# --- historical correctness -------------------------------------------------


def test_price_change_does_not_alter_invoice(api: TestClient) -> None:
    reg = register_business(api)
    ctx = _paid_order(api, reg, sku="NB-PR", price="40.00", qty=3)
    inv = generate_invoice(api, reg.access, ctx["order"]).json()
    # Change the catalog price after issuance.
    api.patch(
        f"/api/products/{ctx['pid']}",
        headers=auth_header(reg.access),
        json={"price": "999.00", "name": "Renamed Notebook"},
    )
    fetched = api.get(f"/api/invoices/{inv['id']}", headers=auth_header(reg.access)).json()
    assert fetched["items"][0]["unit_price"] == "40.00"
    assert fetched["items"][0]["product_name"] == "Notebook"
    assert fetched["total"] == "120.00"


def test_customer_change_does_not_alter_invoice(api: TestClient) -> None:
    reg = register_business(api)
    ctx = _paid_order(api, reg, sku="NB-CU")
    inv = generate_invoice(api, reg.access, ctx["order"]).json()
    original_name = inv["customer_name"]
    api.patch(
        f"/api/customers/{ctx['cust']}",
        headers=auth_header(reg.access),
        json={"name": "Totally Different Name"},
    )
    fetched = api.get(f"/api/invoices/{inv['id']}", headers=auth_header(reg.access)).json()
    assert fetched["customer_name"] == original_name


def test_no_invoice_edit_endpoint(api: TestClient) -> None:
    reg = register_business(api)
    ctx = _paid_order(api, reg, sku="NB-IM")
    inv = generate_invoice(api, reg.access, ctx["order"]).json()
    # Immutable: there is no PATCH/PUT endpoint for invoices.
    assert (
        api.patch(
            f"/api/invoices/{inv['id']}", headers=auth_header(reg.access), json={"total": "1.00"}
        ).status_code
        == 405
    )
