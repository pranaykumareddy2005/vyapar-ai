"""Unit tests for the WhatsApp UX primitives (interaction ids + menu builders)."""

from __future__ import annotations

from app.whatsapp import interactions
from app.whatsapp.menus import ButtonMenu, ListMenu, main_menu, product_card, product_list_menu
from app.whatsapp.roles import WhatsAppRole


def test_interaction_build_and_parse_roundtrip() -> None:
    assert interactions.build(interactions.MENU, "browse") == "menu:browse"
    assert interactions.build(interactions.PRODUCT, 42) == "prod:42"
    assert interactions.build(interactions.NAV, "main") == "nav:main"
    assert interactions.parse("menu:browse") == ("menu", "browse")
    assert interactions.parse("nav") == ("nav", None)
    assert interactions.parse("prod:42") == ("prod", "42")


def test_parse_product_id_validates() -> None:
    assert interactions.parse_product_id("42") == 42
    assert interactions.parse_product_id("0") is None
    assert interactions.parse_product_id("-3") is None
    assert interactions.parse_product_id("abc") is None
    assert interactions.parse_product_id(None) is None


def test_main_menu_is_role_aware() -> None:
    customer = main_menu(WhatsAppRole.CUSTOMER)
    seller = main_menu(WhatsAppRole.STAFF)
    assert isinstance(customer, ButtonMenu) and isinstance(seller, ButtonMenu)
    # Max 3 reply buttons (WhatsApp limit).
    assert len(customer.buttons) <= 3
    assert len(seller.buttons) <= 3
    cust_ids = [bid for bid, _ in customer.buttons]
    seller_ids = [bid for bid, _ in seller.buttons]
    assert "menu:browse" in cust_ids
    assert "menu:add_product" in seller_ids
    assert "menu:add_product" not in cust_ids  # customers cannot add products


class _FakeProduct:
    def __init__(self, pid: int, name: str, price: str, sku: str) -> None:
        self.id = pid
        self.name = name
        self.price_amt = price
        self.sku = sku


def test_product_list_menu_rows_carry_prod_ids() -> None:
    products = [
        _FakeProduct(1, "Notebook", "50.00", "NB-1"),
        _FakeProduct(2, "Pen", "10.00", "PN-1"),
    ]
    menu = product_list_menu(products)  # type: ignore[arg-type]
    assert isinstance(menu, ListMenu)
    assert [rid for rid, _, _ in menu.rows] == ["prod:1", "prod:2"]


def test_product_list_menu_caps_at_ten() -> None:
    products = [_FakeProduct(i, f"P{i}", "1.00", f"S{i}") for i in range(1, 20)]
    menu = product_list_menu(products)  # type: ignore[arg-type]
    assert len(menu.rows) == 10


def test_product_card_has_buy_add_and_menu_buttons() -> None:
    card = product_card(_FakeProduct(7, "Notebook", "50.00", "NB-1"), 27)  # type: ignore[arg-type]
    ids = [bid for bid, _ in card.buttons]
    assert ids == ["buy:7", "cart:add:7", "nav:main"]
    assert "27" in card.body
    assert "Notebook" in card.body
