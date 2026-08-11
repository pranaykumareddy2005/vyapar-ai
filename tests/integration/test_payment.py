"""Integration tests: payment initiation, verification, and order/inventory rules."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.helpers import (
    auth_header,
    create_customer,
    create_inventory,
    create_order,
    create_product,
    initiate_payment,
    register_business,
    transition_order,
    verify_payment,
)


def _confirmed_order(
    api: TestClient, *, price: str = "40.00", qty: int = 2, stock: int = 10
) -> dict:
    reg = register_business(api)
    pid = create_product(api, reg.access, name="Notebook", sku="NB-1", price=price)["id"]
    inv_id = create_inventory(api, reg.access, pid, quantity=stock).json()["id"]
    cust = create_customer(api, reg.access)["id"]
    order = create_order(api, reg.access, cust, [{"product_id": pid, "quantity": qty}]).json()
    transition_order(api, reg.access, order["id"], "CONFIRM")
    return {"reg": reg, "order": order["id"], "inv_id": inv_id, "pid": pid}


def _order_status(api: TestClient, access: str, order_id: int) -> str:
    return api.get(f"/api/orders/{order_id}", headers=auth_header(access)).json()["status"]


def _stock(api: TestClient, access: str, inv_id: int) -> int:
    return api.get(f"/api/inventory/{inv_id}", headers=auth_header(access)).json()["quantity"]


def _movements(api: TestClient, access: str, inv_id: int) -> int:
    return len(api.get(f"/api/inventory/{inv_id}/movements", headers=auth_header(access)).json())


# --- initiation -------------------------------------------------------------


def test_initiate_uses_order_total(api: TestClient) -> None:
    ctx = _confirmed_order(api, price="40.00", qty=2)
    resp = initiate_payment(api, ctx["reg"].access, ctx["order"])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "CREATED"
    assert body["amount"] == "80.00"  # order total, not client-supplied
    assert body["currency"] == "INR"
    assert body["provider_order_id"]
    assert body["payment_url"]
    # Order not yet PAID.
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "CONFIRMED"


def test_initiate_requires_confirmed_order(api: TestClient) -> None:
    reg = register_business(api)
    pid = create_product(api, reg.access, sku="NB-2")["id"]
    create_inventory(api, reg.access, pid, quantity=5)
    cust = create_customer(api, reg.access)["id"]
    order = create_order(api, reg.access, cust, [{"product_id": pid, "quantity": 1}]).json()
    # Order is CREATED, not CONFIRMED.
    assert initiate_payment(api, reg.access, order["id"]).status_code == 409


def test_idempotent_initiation(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    a = api.post(
        "/api/payments",
        headers={**auth_header(ctx["reg"].access), "Idempotency-Key": "init-1"},
        json={"order_id": ctx["order"], "method": "ONLINE"},
    ).json()
    b = api.post(
        "/api/payments",
        headers={**auth_header(ctx["reg"].access), "Idempotency-Key": "init-1"},
        json={"order_id": ctx["order"], "method": "ONLINE"},
    ).json()
    assert a["id"] == b["id"]


# --- successful verification ------------------------------------------------


def test_verify_success_marks_order_paid_without_touching_inventory(api: TestClient) -> None:
    ctx = _confirmed_order(api, qty=2, stock=10)
    assert _stock(api, ctx["reg"].access, ctx["inv_id"]) == 8  # decremented on confirm
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"]).json()
    resp = verify_payment(api, ctx["reg"].access, payment["id"], "pay_ok_1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "PAID"
    # Payment must NOT modify inventory: stock and movement count unchanged.
    assert _stock(api, ctx["reg"].access, ctx["inv_id"]) == 8
    assert _movements(api, ctx["reg"].access, ctx["inv_id"]) == 1


def test_order_not_paid_before_verification(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    initiate_payment(api, ctx["reg"].access, ctx["order"])
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "CONFIRMED"


def test_initiate_rejected_when_already_paid(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"]).json()
    verify_payment(api, ctx["reg"].access, payment["id"], "pay_ok_1")
    assert initiate_payment(api, ctx["reg"].access, ctx["order"]).status_code == 409


# --- failed / mismatch verification -----------------------------------------


def _verify_expect_fail(api: TestClient, ctx: dict, pid: str, code: int) -> dict:
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"]).json()
    resp = verify_payment(api, ctx["reg"].access, payment["id"], pid)
    assert resp.status_code == code, resp.text
    # Order never becomes PAID on a failed/mismatched verification.
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "CONFIRMED"
    # The payment record reflects FAILED (mismatch/failure) or CREATED (transient).
    got = api.get(f"/api/payments/{payment['id']}", headers=auth_header(ctx["reg"].access)).json()
    return got


def test_amount_mismatch_fails(api: TestClient) -> None:
    got = _verify_expect_fail(api, _confirmed_order(api), "pay_amount_1", 422)
    assert got["status"] == "FAILED"
    assert got["failure_code"] == "amount_mismatch"


def test_currency_mismatch_fails(api: TestClient) -> None:
    got = _verify_expect_fail(api, _confirmed_order(api), "pay_currency_1", 422)
    assert got["failure_code"] == "currency_mismatch"


def test_reference_mismatch_fails(api: TestClient) -> None:
    got = _verify_expect_fail(api, _confirmed_order(api), "pay_order_1", 422)
    assert got["failure_code"] == "reference_mismatch"


def test_provider_reported_failure(api: TestClient) -> None:
    got = _verify_expect_fail(api, _confirmed_order(api), "pay_fail_1", 422)
    assert got["status"] == "FAILED"


def test_provider_unavailable_leaves_payment_retryable(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"]).json()
    resp = verify_payment(api, ctx["reg"].access, payment["id"], "pay_unavailable_1")
    assert resp.status_code == 502
    got = api.get(f"/api/payments/{payment['id']}", headers=auth_header(ctx["reg"].access)).json()
    assert got["status"] == "CREATED"  # not marked FAILED; can retry
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "CONFIRMED"


def test_pending_then_success(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"]).json()
    pending = verify_payment(api, ctx["reg"].access, payment["id"], "pay_pending_1")
    assert pending.json()["status"] == "PENDING"
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "CONFIRMED"
    # A later successful verification of the same (still-pending) payment works.
    ok = verify_payment(api, ctx["reg"].access, payment["id"], "pay_ok_1")
    assert ok.json()["status"] == "SUCCESS"
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "PAID"


# --- duplicate / idempotency ------------------------------------------------


def test_duplicate_verification_is_idempotent(api: TestClient) -> None:
    ctx = _confirmed_order(api, qty=2)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"]).json()
    first = verify_payment(api, ctx["reg"].access, payment["id"], "pay_ok_1").json()
    second = verify_payment(api, ctx["reg"].access, payment["id"], "pay_ok_1").json()
    assert first["status"] == second["status"] == "SUCCESS"
    assert first["id"] == second["id"]
    # Exactly one payment, order PAID, one inventory movement (from confirm only).
    assert len(api.get("/api/payments", headers=auth_header(ctx["reg"].access)).json()) == 1
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "PAID"
    assert _movements(api, ctx["reg"].access, ctx["inv_id"]) == 1


def test_verify_failed_payment_cannot_be_reverified(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"]).json()
    verify_payment(api, ctx["reg"].access, payment["id"], "pay_fail_1")  # -> FAILED
    # Re-verifying a terminal FAILED payment is a conflict (retry = new attempt).
    resp = verify_payment(api, ctx["reg"].access, payment["id"], "pay_ok_1")
    assert resp.status_code == 409


# --- COD --------------------------------------------------------------------


def test_verify_rejects_cod_payment(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"], method="COD").json()
    assert verify_payment(api, ctx["reg"].access, payment["id"], "pay_ok_1").status_code == 409


def test_confirm_cod_rejects_online_payment(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"], method="ONLINE").json()
    resp = api.post(
        f"/api/payments/{payment['id']}/confirm-cod", headers=auth_header(ctx["reg"].access)
    )
    assert resp.status_code == 409


def test_cod_confirmation(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"], method="COD").json()
    assert payment["provider"] == "cod"
    resp = api.post(
        f"/api/payments/{payment['id']}/confirm-cod", headers=auth_header(ctx["reg"].access)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"
    assert _order_status(api, ctx["reg"].access, ctx["order"]) == "PAID"


# --- history ----------------------------------------------------------------


def test_payment_history_and_detail(api: TestClient) -> None:
    ctx = _confirmed_order(api)
    payment = initiate_payment(api, ctx["reg"].access, ctx["order"]).json()
    listing = api.get("/api/payments", headers=auth_header(ctx["reg"].access)).json()
    assert [p["id"] for p in listing] == [payment["id"]]
    detail = api.get(
        f"/api/payments/{payment['id']}", headers=auth_header(ctx["reg"].access)
    ).json()
    assert detail["order_id"] == ctx["order"]
