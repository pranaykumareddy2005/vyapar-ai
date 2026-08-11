"""Invoice persistence. Tenant-scoped by ``business_id``; persistence-only.

``InvoiceCounterRepository.next_sequence`` allocates a gap-free per-business-per-
year sequence with an atomic Postgres UPSERT; the conflicting row is locked until
the surrounding transaction commits, so concurrent invoice generation is
serialized and never produces duplicate numbers (LLD §7.4).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.invoice.models import Invoice, InvoiceCounter, InvoiceItem


class InvoiceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, invoice: Invoice) -> Invoice:
        self._session.add(invoice)
        self._session.flush()
        return invoice

    def get(self, business_id: int, invoice_id: int) -> Invoice | None:
        stmt = select(Invoice).where(Invoice.id == invoice_id, Invoice.business_id == business_id)
        return self._session.scalars(stmt).one_or_none()

    def get_by_order(self, business_id: int, order_id: int) -> Invoice | None:
        stmt = select(Invoice).where(
            Invoice.business_id == business_id, Invoice.order_id == order_id
        )
        return self._session.scalars(stmt).one_or_none()

    def list(self, business_id: int) -> list[Invoice]:
        stmt = select(Invoice).where(Invoice.business_id == business_id).order_by(Invoice.id.desc())
        return list(self._session.scalars(stmt).all())


class InvoiceItemRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, item: InvoiceItem) -> InvoiceItem:
        self._session.add(item)
        self._session.flush()
        return item


class InvoiceCounterRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def next_sequence(self, business_id: int, year: int) -> int:
        """Atomically allocate the next sequence for (business, year).

        A single UPSERT: insert ``next_seq=1`` for a new (business, year), else
        increment the existing row and return the new value. The increment shares
        the caller's transaction, so a rolled-back invoice insert also rolls back
        the increment (no gaps).
        """
        stmt = (
            pg_insert(InvoiceCounter)
            .values(business_id=business_id, year=year, next_seq=1)
            .on_conflict_do_update(
                index_elements=[InvoiceCounter.business_id, InvoiceCounter.year],
                set_={"next_seq": InvoiceCounter.next_seq + 1},
            )
            .returning(InvoiceCounter.next_seq)
        )
        return self._session.execute(stmt).scalar_one()
