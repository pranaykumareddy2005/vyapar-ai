"""FastAPI wiring for the AI catalog service.

Composes the draft repository, the catalog application boundary (reused, not
re-implemented), the configured AI provider, and object storage.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.catalog.dependencies import get_catalog_service
from app.catalog.service import CatalogService
from app.catalogai.provider import AiProvider
from app.catalogai.repository import CatalogAiDraftRepository
from app.catalogai.service import CatalogAiService
from app.common.storage import ObjectStorage
from app.db import get_session
from app.providers import get_ai_provider, get_object_storage


def get_catalog_ai_service(
    session: Session = Depends(get_session),
    catalog: CatalogService = Depends(get_catalog_service),
    provider: AiProvider = Depends(get_ai_provider),
    storage: ObjectStorage = Depends(get_object_storage),
) -> CatalogAiService:
    return CatalogAiService(
        session,
        CatalogAiDraftRepository(session),
        catalog,
        provider,
        storage,
    )
