"""Integration tests for the WhatsApp Rich Chat UX foundation (Phase A).

Drives the real webhook -> router -> existing domain services, asserting the
interactive experience: main menu, buttons, list menus, session state, role
resolution, mark_read, deterministic id routing, and safe handling - all while
product data comes only from CatalogService / InventoryService.
"""

from __future__ import annotations

from typing import Any

from app.business.models import Business
from app.providers import get_messaging_provider
from app.whatsapp.models import WhatsAppStaff
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.helpers import create_inventory, create_product, register_business

WEBHOOK = "/webhooks/whatsapp"
PNID_A = "111111111111111"
PNID_B = "222222222222222"
SENDER = "919111111111"
STAFF_PHONE = "919999999999"


def _link(db: Session, business_id: int, pnid: str) -> None:
    biz = db.get(Business, business_id)
    assert biz is not None
    biz.whatsapp_phone_number_id = pnid
    db.flush()


def _seed_staff(db: Session, business_id: int, phone: str) -> None:
    db.add(WhatsAppStaff(business_id=business_id, phone=phone))
    db.flush()


def _messaging() -> Any:
    provider = get_messaging_provider()
    provider.clear()
    return provider


def _text(text: str, *, mid: str = "wamid.t", sender: str = SENDER, pnid: str = PNID_A) -> dict:
    return _wrap({"from": sender, "id": mid, "type": "text", "text": {"body": text}}, pnid, sender)


def _interactive(
    interaction_id: str,
    *,
    mid: str = "wamid.i",
    title: str = "x",
    kind: str = "button",
    sender: str = SENDER,
    pnid: str = PNID_A,
) -> dict:
    reply_key = "button_reply" if kind == "button" else "list_reply"
    msg = {
        "from": sender,
        "id": mid,
        "type": "interactive",
        "interactive": {"type": reply_key, reply_key: {"id": interaction_id, "title": title}},
    }
    return _wrap(msg, pnid, sender)


def _image(*, mid: str = "wamid.img", sender: str = SENDER, pnid: str = PNID_A) -> dict:
    msg = {
        "from": sender,
        "id": mid,
        "type": "image",
        "image": {"id": "MEDIA1", "mime_type": "image/jpeg"},
    }
    return _wrap(msg, pnid, sender)


def _wrap(message: dict, pnid: str, sender: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": pnid},
                            "contacts": [{"profile": {"name": "Asha"}, "wa_id": sender}],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


# --- main menu + role -------------------------------------------------------


def test_greeting_shows_customer_menu(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    resp = api.post(WEBHOOK, json=_text("hi"))
    assert resp.status_code == 200
    assert len(m.buttons) == 1
    ids = [bid for bid, _ in m.buttons[0]["buttons"]]
    assert "menu:browse" in ids and "menu:add_product" not in ids


def test_greeting_shows_seller_menu_for_staff(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    _seed_staff(db_session, reg.business_id, STAFF_PHONE)
    m = _messaging()
    resp = api.post(WEBHOOK, json=_text("hi", sender=STAFF_PHONE, mid="wamid.staff"))
    assert resp.status_code == 200
    ids = [bid for bid, _ in m.buttons[0]["buttons"]]
    assert "menu:add_product" in ids  # seller-only entry


def test_mark_read_called_for_inbound(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    api.post(WEBHOOK, json=_text("hi", mid="wamid.mr"))
    assert "wamid.mr" in m.read_receipts


# --- browse / list menu -----------------------------------------------------


def test_browse_button_lists_real_catalogue(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    p1 = create_product(api, reg.access, name="Notebook", sku="NB-1")
    create_product(api, reg.access, name="Pen", sku="PN-1")
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    api.post(WEBHOOK, json=_interactive("menu:browse"))
    assert len(m.lists) == 1
    row_ids = [rid for rid, _, _ in m.lists[0]["rows"]]
    assert f"prod:{p1['id']}" in row_ids


def test_empty_catalogue_browse_is_graceful(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    api.post(WEBHOOK, json=_interactive("menu:browse"))
    assert m.lists == []
    assert m.last_to(SENDER) is not None  # a friendly text instead


# --- search via session state ----------------------------------------------


def test_search_prompt_then_results_uses_session_state(
    api: TestClient, db_session: Session
) -> None:
    reg = register_business(api)
    create_product(api, reg.access, name="Notebook", sku="NB-1")
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    # Tap Search -> prompt (sets AWAITING_SEARCH)
    api.post(WEBHOOK, json=_interactive("menu:search", mid="wamid.s1"))
    assert m.last_to(SENDER) is not None
    # Next free text is treated as the search query (session state), not NL.
    api.post(WEBHOOK, json=_text("notebook", mid="wamid.s2"))
    assert len(m.lists) == 1
    row_ids = [rid for rid, _, _ in m.lists[0]["rows"]]
    assert any(r.startswith("prod:") for r in row_ids)


# --- stock via session state ------------------------------------------------


def test_stock_prompt_then_real_quantity(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = create_product(api, reg.access, name="Notebook", sku="NB-1")
    create_inventory(api, reg.access, product["id"], quantity=27)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    api.post(WEBHOOK, json=_interactive("menu:stock", mid="wamid.k1"))
    api.post(WEBHOOK, json=_text("notebook", mid="wamid.k2"))
    reply = m.last_to(SENDER)
    assert reply is not None and "27" in reply.text  # real inventory number


# --- product card + buy stub ------------------------------------------------


def test_product_row_shows_card(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = create_product(api, reg.access, name="Notebook", sku="NB-1")
    create_inventory(api, reg.access, product["id"], quantity=27)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    api.post(WEBHOOK, json=_interactive(f"prod:{product['id']}", kind="list"))
    assert len(m.buttons) == 1
    ids = [bid for bid, _ in m.buttons[0]["buttons"]]
    assert ids == [f"buy:{product['id']}", f"cart:add:{product['id']}", "nav:main"]
    assert "27" in str(m.buttons[0]["body"])


def test_buy_is_deterministic_stub(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = create_product(api, reg.access, name="Notebook", sku="NB-1")
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    api.post(WEBHOOK, json=_interactive(f"buy:{product['id']}"))
    reply = m.last_to(SENDER)
    assert reply is not None  # honest "coming next" placeholder, no fabricated order


def test_nav_main_returns_menu(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    api.post(WEBHOOK, json=_interactive("nav:main"))
    assert len(m.buttons) == 1


# --- robustness -------------------------------------------------------------


def test_unknown_interaction_falls_back_to_menu(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    resp = api.post(WEBHOOK, json=_interactive("bogus:action"))
    assert resp.status_code == 200
    assert len(m.buttons) == 1  # safe fallback to main menu


def test_malformed_interactive_is_unsupported(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    bad = _wrap(
        {
            "from": SENDER,
            "id": "wamid.bad",
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"title": "no id"}},
        },
        PNID_A,
        SENDER,
    )
    resp = api.post(WEBHOOK, json=bad)
    assert resp.status_code == 200
    assert m.last_to(SENDER) is not None  # graceful unsupported reply


def test_duplicate_interaction_processed_once(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    create_product(api, reg.access, name="Notebook", sku="NB-1")
    _link(db_session, reg.business_id, PNID_A)
    _messaging()
    payload = _interactive("menu:browse", mid="wamid.dupint")
    first = api.post(WEBHOOK, json=payload)
    second = api.post(WEBHOOK, json=payload)
    assert first.json()["processed"] == 1
    assert second.json()["duplicates"] == 1


# --- tenant isolation of role ----------------------------------------------


def test_staff_role_is_per_business(api: TestClient, db_session: Session) -> None:
    a = register_business(api, email="a@shop.co", name="Shop A")
    _link(db_session, a.business_id, PNID_A)
    b = register_business(api, email="b@shop.co", name="Shop B")
    _link(db_session, b.business_id, PNID_B)
    # STAFF_PHONE is staff of A only.
    _seed_staff(db_session, a.business_id, STAFF_PHONE)
    m = _messaging()
    # Same phone messaging business B's line is a plain customer there.
    api.post(WEBHOOK, json=_text("hi", sender=STAFF_PHONE, pnid=PNID_B, mid="wamid.iso"))
    ids = [bid for bid, _ in m.buttons[0]["buttons"]]
    assert "menu:add_product" not in ids  # not staff of B


# --- seller media foundation ------------------------------------------------


def test_seller_image_acknowledged(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _link(db_session, reg.business_id, PNID_A)
    _seed_staff(db_session, reg.business_id, STAFF_PHONE)
    m = _messaging()
    resp = api.post(WEBHOOK, json=_image(sender=STAFF_PHONE, mid="wamid.simg"))
    assert resp.status_code == 200
    assert m.last_to(STAFF_PHONE) is not None


# --- safe handling of Meta send failures -----------------------------------


class _FailingChannel:
    """A WhatsAppChannel whose every send fails (e.g. non-deliverable recipient)."""

    def _boom(self, *_a: object, **_k: object) -> Any:
        from app.whatsapp.provider import MetaWhatsAppInvalidRecipient

        raise MetaWhatsAppInvalidRecipient("meta rejected the request (400)")

    send = _boom
    send_buttons = _boom
    send_list = _boom
    send_image = _boom
    send_document = _boom
    upload_media = _boom
    download_media = _boom

    def mark_read(self, message_id: str) -> bool:
        return False


def test_meta_send_failure_never_5xxs_the_webhook(api: TestClient, db_session: Session) -> None:
    from app.providers import get_messaging_provider

    reg = register_business(api)
    create_product(api, reg.access, name="Notebook", sku="NB-1")
    _link(db_session, reg.business_id, PNID_A)
    api.app.dependency_overrides[get_messaging_provider] = lambda: _FailingChannel()
    try:
        # Free-form text -> ConversationService -> send fails -> must be contained.
        r1 = api.post(WEBHOOK, json=_text("how many notebooks?", mid="wamid.f1"))
        # Interactive -> menu send fails -> must be contained.
        r2 = api.post(WEBHOOK, json=_interactive("menu:browse", mid="wamid.f2"))
    finally:
        api.app.dependency_overrides.pop(get_messaging_provider, None)
    assert r1.status_code == 200 and r1.json()["processed"] == 1
    assert r2.status_code == 200 and r2.json()["processed"] == 1


# --- free-form NL still routes to catalogue (regression) -------------------


def test_free_form_question_uses_conversation_service(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    product = create_product(api, reg.access, name="Notebook", sku="NB-1")
    create_inventory(api, reg.access, product["id"], quantity=27)
    _link(db_session, reg.business_id, PNID_A)
    m = _messaging()
    # A natural-language question (deterministic mock AI resolves "notebooks").
    api.post(WEBHOOK, json=_text("how many notebooks?", mid="wamid.nl"))
    reply = m.last_to(SENDER)
    assert reply is not None and "27" in reply.text
