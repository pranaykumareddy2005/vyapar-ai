"""End-to-end WhatsApp commerce journey (M14-M18).

Seller: photo -> AI draft -> Publish -> REAL catalogue product.
Customer: card -> cart -> checkout -> address -> REAL order -> payment ->
server-side verification -> REAL invoice PDF over WhatsApp -> tracking.

Uses the deterministic mock AI + mock payment/messaging providers (test env), so
the whole journey runs offline while every business fact still comes from the
domain services.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.helpers import (
    auth_header,
    create_inventory,
    create_product,
    register_business,
)
from tests.integration.test_whatsapp_ux_flow import (
    PNID_A,
    SENDER,
    STAFF_PHONE,
    WEBHOOK,
    _interactive,
    _link,
    _messaging,
    _seed_staff,
    _text,
    _wrap,
)


def _image(caption: str | None = None, *, mid: str = "wamid.img", sender: str = SENDER) -> dict:
    msg: dict[str, Any] = {
        "from": sender,
        "id": mid,
        "type": "image",
        "image": {"id": "MEDIA1", "mime_type": "image/jpeg"},
    }
    if caption is not None:
        msg["image"]["caption"] = caption
    return _wrap(msg, PNID_A, sender)


# ============================ M14: SELLER ============================


def test_seller_photo_with_price_shows_review_card(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    _seed_staff(db_session, reg.business_id, STAFF_PHONE)
    m = _messaging()
    resp = api.post(WEBHOOK, json=_image("150 rupees", sender=STAFF_PHONE, mid="wamid.p1"))
    assert resp.status_code == 200
    assert len(m.buttons) == 1
    ids = [bid for bid, _ in m.buttons[0]["buttons"]]
    assert any(b.startswith("pub:") for b in ids)
    assert any(b.startswith("canceldraft:") for b in ids)


def test_seller_publish_creates_real_catalogue_product(
    api: TestClient, db_session: Session
) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    _seed_staff(db_session, reg.business_id, STAFF_PHONE)
    m = _messaging()
    # Photo + price -> review card
    api.post(WEBHOOK, json=_image("150", sender=STAFF_PHONE, mid="wamid.p2"))
    draft_button = next(b for b, _ in m.buttons[0]["buttons"] if b.startswith("pub:"))
    # Tap Publish
    api.post(WEBHOOK, json=_interactive(draft_button, sender=STAFF_PHONE, mid="wamid.pub"))
    # The product now exists in the REAL catalogue (via the authenticated API).
    products = api.get("/api/products", headers=auth_header(reg.access)).json()
    assert any(p["name"] == "Sample Product" for p in products)


def test_seller_photo_without_price_prompts_then_publishes(
    api: TestClient, db_session: Session
) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    _seed_staff(db_session, reg.business_id, STAFF_PHONE)
    m = _messaging()
    api.post(WEBHOOK, json=_image(sender=STAFF_PHONE, mid="wamid.p3"))  # no caption
    assert m.last_to(STAFF_PHONE) is not None  # asked for price
    api.post(WEBHOOK, json=_text("250", sender=STAFF_PHONE, mid="wamid.price"))
    assert len(m.buttons) == 1  # review card now shown
    ids = [bid for bid, _ in m.buttons[0]["buttons"]]
    assert any(b.startswith("pub:") for b in ids)


def test_seller_cancel_draft(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    _seed_staff(db_session, reg.business_id, STAFF_PHONE)
    m = _messaging()
    api.post(WEBHOOK, json=_image("150", sender=STAFF_PHONE, mid="wamid.p4"))
    cancel_btn = next(b for b, _ in m.buttons[0]["buttons"] if b.startswith("canceldraft:"))
    api.post(WEBHOOK, json=_interactive(cancel_btn, sender=STAFF_PHONE, mid="wamid.cxl"))
    products = api.get("/api/products", headers=auth_header(reg.access)).json()
    assert products == []  # nothing published


def test_customer_photo_is_not_seller_flow(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)  # SENDER is a plain customer
    m = _messaging()
    api.post(WEBHOOK, json=_image("150", mid="wamid.cust_img"))
    assert not m.buttons  # no seller review card for a customer
    assert m.last_to(SENDER) is not None  # graceful unsupported reply


def test_customer_cannot_use_seller_publish_button(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    # A customer forging a seller publish id gets the main menu, not a publish.
    api.post(WEBHOOK, json=_interactive("pub:1", mid="wamid.forge"))
    assert len(m.buttons) == 1
    ids = [bid for bid, _ in m.buttons[0]["buttons"]]
    assert "menu:browse" in ids  # customer menu (not published anything)


# ============================ M15: CART ============================


def _seed_catalogue(api: TestClient, reg: Any, *, qty: int = 27) -> dict:
    product = create_product(api, reg.access, name="Notebook", sku="NB-1")
    create_inventory(api, reg.access, product["id"], quantity=qty)
    return product


def test_add_to_cart_and_view(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = _seed_catalogue(api, reg)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    api.post(WEBHOOK, json=_interactive(f"cart:add:{product['id']}", mid="wamid.add"))
    assert m.buttons  # "added" confirmation with checkout button
    m.clear()
    api.post(WEBHOOK, json=_interactive("cart:view", mid="wamid.cv"))
    assert len(m.lists) == 1
    assert "50" in str(m.lists[0]["body"])  # cart total from real price


def test_cart_increment_and_remove(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = _seed_catalogue(api, reg)
    pid = product["id"]
    _link(db_session, reg.business_id, PNID_A)
    _messaging()
    api.post(WEBHOOK, json=_interactive(f"cart:add:{pid}", mid="wamid.a1"))
    m = _messaging()
    api.post(WEBHOOK, json=_interactive(f"cart:inc:{pid}", mid="wamid.inc"))
    assert "100" in str(m.lists[-1]["body"])  # 2 x 50
    m.clear()
    api.post(WEBHOOK, json=_interactive(f"cart:rm:{pid}", mid="wamid.rm"))
    # After removal the cart is empty (view shows empty text, no list).
    assert m.last_to(SENDER) is not None


# ============================ M16-M18: BUY -> ORDER -> PAY -> INVOICE ============================


def _buy_to_order(api: TestClient, db_session: Session, reg: Any, product: dict) -> None:
    """Drive buy -> checkout -> address -> order for SENDER."""
    api.post(WEBHOOK, json=_interactive(f"buy:{product['id']}", mid="wamid.buy"))
    # No saved address -> address prompt -> reply address -> order + payment
    api.post(WEBHOOK, json=_text("12 MG Road, Bengaluru, 560001", mid="wamid.addr"))


def test_full_checkout_creates_confirmed_order(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = _seed_catalogue(api, reg, qty=10)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    _buy_to_order(api, db_session, reg, product)
    # A real order now exists and is CONFIRMED (stock decremented 10 -> 9).
    orders = api.get("/api/orders", headers=auth_header(reg.access)).json()
    assert len(orders) == 1
    assert orders[0]["status"] == "CONFIRMED"
    inv = api.get("/api/inventory", headers=auth_header(reg.access)).json()
    assert inv[0]["quantity"] == 9
    # A payment link + "I've paid" button was sent.
    assert any("payverify:" in b for grp in m.buttons for b, _ in grp["buttons"])


def test_payment_verify_marks_paid_and_sends_invoice(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = _seed_catalogue(api, reg, qty=10)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    _buy_to_order(api, db_session, reg, product)
    verify_btn = next(
        b for grp in m.buttons for b, _ in grp["buttons"] if b.startswith("payverify:")
    )
    m.clear()
    api.post(WEBHOOK, json=_interactive(verify_btn, mid="wamid.pay"))
    # Order is now PAID and a real invoice PDF was delivered as a document.
    orders = api.get("/api/orders", headers=auth_header(reg.access)).json()
    assert orders[0]["status"] == "PAID"
    assert len(m.documents) == 1
    assert m.documents[0]["filename"].endswith(".pdf")


def test_order_tracking_shows_status(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = _seed_catalogue(api, reg, qty=10)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    _buy_to_order(api, db_session, reg, product)
    order_id = api.get("/api/orders", headers=auth_header(reg.access)).json()[0]["id"]
    m.clear()
    api.post(WEBHOOK, json=_interactive("menu:orders", mid="wamid.trk"))
    assert len(m.lists) == 1  # order list
    m.clear()
    api.post(WEBHOOK, json=_interactive(f"order:{order_id}", mid="wamid.ord"))
    reply = m.last_to(SENDER)
    assert reply is not None and f"#{order_id}" in reply.text


def test_customer_cannot_view_other_customers_order(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = _seed_catalogue(api, reg, qty=10)
    _link(db_session, reg.business_id, PNID_A)
    _messaging()
    _buy_to_order(api, db_session, reg, product)
    order_id = api.get("/api/orders", headers=auth_header(reg.access)).json()[0]["id"]
    # A DIFFERENT customer phone asks for that order id -> "not found".
    m = _messaging()
    other = _wrap(
        {
            "from": "919222222222",
            "id": "wamid.other",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": f"order:{order_id}", "title": "x"},
            },
        },
        PNID_A,
        "919222222222",
    )
    api.post(WEBHOOK, json=other)
    reply = m.last_to("919222222222")
    assert reply is not None and "not found" in reply.text.lower()


# ============================ ROBUSTNESS ============================


def test_duplicate_buy_press_creates_one_order(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = _seed_catalogue(api, reg, qty=10)
    _link(db_session, reg.business_id, PNID_A)
    _messaging()
    # Same wamid twice for the buy tap.
    payload = _interactive(f"buy:{product['id']}", mid="wamid.dupbuy")
    api.post(WEBHOOK, json=payload)
    api.post(WEBHOOK, json=payload)  # duplicate -> ignored
    api.post(WEBHOOK, json=_text("12 MG Road, Bengaluru, 560001", mid="wamid.dupaddr"))
    orders = api.get("/api/orders", headers=auth_header(reg.access)).json()
    assert len(orders) == 1  # exactly one order


def test_checkout_empty_cart_is_graceful(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    resp = api.post(WEBHOOK, json=_interactive("checkout", mid="wamid.empty"))
    assert resp.status_code == 200
    assert m.last_to(SENDER) is not None  # "cart is empty"


def test_buy_nonexistent_product_is_graceful(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    resp = api.post(WEBHOOK, json=_interactive("prod:999999", kind="list", mid="wamid.nope"))
    assert resp.status_code == 200
    assert m.last_to(SENDER) is not None  # "no longer available"
