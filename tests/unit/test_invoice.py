"""Unit tests: invoice schema, PDF rendering, and numbering format."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.invoice.models import Invoice, InvoiceItem, InvoiceStatus
from app.invoice.pdf import render_invoice_pdf
from app.invoice.schemas import InvoiceCreate


def _invoice() -> Invoice:
    inv = Invoice(
        id=1,
        business_id=1,
        order_id=1,
        invoice_number="INV-2026-0001",
        status=InvoiceStatus.ISSUED,
        issued_at=datetime.now(UTC),
        currency="INR",
        subtotal_amt=Decimal("120.00"),
        tax_amt=Decimal("0.00"),
        total_amt=Decimal("120.00"),
        customer_name="Asha Verma",
        customer_phone="+919111111111",
        business_name="Test Shop",
        payment_method="ONLINE",
        payment_reference="pay_ok_1",
        payment_status="PAID",
    )
    inv.items = [
        InvoiceItem(
            id=1,
            business_id=1,
            invoice_id=1,
            product_id=1,
            product_name="Notebook",
            unit_price=Decimal("40.00"),
            quantity=3,
            line_total=Decimal("120.00"),
        )
    ]
    return inv


def test_invoice_create_schema() -> None:
    assert InvoiceCreate(order_id=5).order_id == 5


def test_pdf_is_non_empty_pdf() -> None:
    pdf = render_invoice_pdf(_invoice())
    assert isinstance(pdf, bytes)
    assert len(pdf) > 500
    assert pdf.startswith(b"%PDF")


def test_pdf_contains_invoice_content() -> None:
    from pypdf import PdfReader

    pdf = render_invoice_pdf(_invoice())
    from io import BytesIO

    text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    assert "INV-2026-0001" in text
    assert "Asha Verma" in text
    assert "Notebook" in text
    assert "120.00" in text  # total
    assert "Test Shop" in text


def test_pdf_is_deterministic_from_snapshot() -> None:
    # Same snapshot -> identical rendered content (the renderer reads only the
    # snapshot; raw bytes carry a creation timestamp, so compare extracted text).
    from io import BytesIO

    from pypdf import PdfReader

    inv = _invoice()

    def _text(pdf: bytes) -> str:
        return "".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages)

    assert _text(render_invoice_pdf(inv)) == _text(render_invoice_pdf(inv))
