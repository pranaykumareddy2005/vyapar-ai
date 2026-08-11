"""Invoice PDF renderer (reportlab).

Renders bytes from the *immutable invoice snapshot only* - it reads no Product,
Customer, or Order table. Given the same invoice it produces the same document.
``reportlab`` is the project's declared ``pdf`` extra; it is imported lazily so the
core package installs without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.invoice.models import Invoice


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """Return the invoice as PDF bytes, built from its stored snapshot fields."""
    import io

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 20 * mm
    y = height - 25 * mm

    def line(text: str, *, size: int = 10, dy: float = 6 * mm, bold: bool = False) -> None:
        nonlocal y
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(left, y, text)
        y -= dy

    line(invoice.business_name or "Invoice", size=16, bold=True, dy=9 * mm)
    line(f"Invoice: {invoice.invoice_number}", size=11, bold=True)
    line(f"Status: {invoice.status.value}    Payment: {invoice.payment_status}")
    line(f"Bill To: {invoice.customer_name}  ({invoice.customer_phone})")
    y -= 3 * mm

    # Column headers.
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left, y, "Item")
    pdf.drawString(left + 80 * mm, y, "Qty")
    pdf.drawString(left + 100 * mm, y, "Unit")
    pdf.drawString(left + 130 * mm, y, "Line total")
    y -= 3 * mm
    pdf.line(left, y, width - 20 * mm, y)
    y -= 6 * mm

    pdf.setFont("Helvetica", 10)
    for item in invoice.items:
        pdf.drawString(left, y, str(item.product_name)[:40])
        pdf.drawString(left + 80 * mm, y, str(item.quantity))
        pdf.drawString(left + 100 * mm, y, f"{invoice.currency} {item.unit_price}")
        pdf.drawString(left + 130 * mm, y, f"{invoice.currency} {item.line_total}")
        y -= 6 * mm

    y -= 3 * mm
    pdf.line(left + 100 * mm, y, width - 20 * mm, y)
    y -= 7 * mm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(left + 100 * mm, y, f"Subtotal: {invoice.currency} {invoice.subtotal_amt}")
    y -= 6 * mm
    pdf.drawString(left + 100 * mm, y, f"Tax: {invoice.currency} {invoice.tax_amt}")
    y -= 6 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.setFillColor(colors.black)
    pdf.drawString(left + 100 * mm, y, f"Total: {invoice.currency} {invoice.total_amt}")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
