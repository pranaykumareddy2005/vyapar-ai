"""AI catalog draft persistence. Every query is tenant-scoped by ``business_id``.

Persistence only - no business rules here (those live in ``CatalogAiService``).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogai.models import CatalogAiDraft


class CatalogAiDraftRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, draft: CatalogAiDraft) -> CatalogAiDraft:
        self._session.add(draft)
        self._session.flush()
        return draft

    def get(self, business_id: int, draft_id: int) -> CatalogAiDraft | None:
        stmt = select(CatalogAiDraft).where(
            CatalogAiDraft.id == draft_id,
            CatalogAiDraft.business_id == business_id,
        )
        return self._session.scalars(stmt).one_or_none()

    def get_by_request_key(self, business_id: int, request_key: str) -> CatalogAiDraft | None:
        stmt = select(CatalogAiDraft).where(
            CatalogAiDraft.business_id == business_id,
            CatalogAiDraft.request_key == request_key,
        )
        return self._session.scalars(stmt).first()

    def list(self, business_id: int) -> list[CatalogAiDraft]:
        stmt = (
            select(CatalogAiDraft)
            .where(CatalogAiDraft.business_id == business_id)
            .order_by(CatalogAiDraft.id.desc())
        )
        return list(self._session.scalars(stmt).all())
