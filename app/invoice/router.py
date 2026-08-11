"""Invoice API - thin controllers over InvoiceService.

business_id comes from the authenticated principal only. Generation requires
OWNER/EMPLOYEE; read/list/pdf require any authenticated principal. Invoices are
immutable - there is no edit endpoint. The client never supplies financial values.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response

from app.auth.dependencies import Principal, get_current_principal, require_role
from app.common.security import Role
from app.invoice.dependencies import get_invoice_service
from app.invoice.schemas import InvoiceCreate, InvoiceOut
from app.invoice.service import InvoiceService

router = APIRouter(prefix="/api/invoices", tags=["invoices"])

_MUTATOR_ROLES = (Role.OWNER, Role.EMPLOYEE)


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def generate_invoice(
    payload: InvoiceCreate,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: InvoiceService = Depends(get_invoice_service),
) -> InvoiceOut:
    invoice = service.generate(principal.business_id, payload.order_id)
    return InvoiceOut.from_model(invoice)


@router.get("", response_model=list[InvoiceOut])
def list_invoices(
    principal: Principal = Depends(get_current_principal),
    service: InvoiceService = Depends(get_invoice_service),
) -> list[InvoiceOut]:
    return [InvoiceOut.from_model(i) for i in service.list_invoices(principal.business_id)]


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int,
    principal: Principal = Depends(get_current_principal),
    service: InvoiceService = Depends(get_invoice_service),
) -> InvoiceOut:
    return InvoiceOut.from_model(service.get(principal.business_id, invoice_id))


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    principal: Principal = Depends(get_current_principal),
    service: InvoiceService = Depends(get_invoice_service),
) -> Response:
    pdf_bytes = service.get_pdf(principal.business_id, invoice_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="invoice-{invoice_id}.pdf"'},
    )
