"""AI Catalog Generator API - thin controllers over CatalogAiService.

Authorization uses the authenticated principal's ``business_id`` exclusively; no
endpoint accepts a client-supplied business id. Generation, edit, approval,
rejection and regeneration are OWNER/EMPLOYEE actions (RBAC), consistent with
``POST /api/products``. Approval is not PIN-gated: FR-AUTH-03 reserves the
Business PIN for destructive actions, and creating a product is not one (see
docs/history/phase4_schema_decision.md D7).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status

from app.auth.dependencies import (
    Principal,
    get_current_principal,
    require_role,
)
from app.catalog.schemas import ProductOut
from app.catalogai.dependencies import get_catalog_ai_service
from app.catalogai.models import CatalogAiDraft
from app.catalogai.schemas import DraftEdit, DraftOut
from app.catalogai.service import CatalogAiService
from app.common.security import Role
from app.config import Settings, get_settings

router = APIRouter(prefix="/api/catalog-ai", tags=["catalog-ai"])

_MUTATOR_ROLES = (Role.OWNER, Role.EMPLOYEE)


def _out(draft: CatalogAiDraft, settings: Settings) -> DraftOut:
    return DraftOut.from_model(draft, confidence_threshold=settings.ai_confidence_threshold)


@router.post("/drafts", response_model=DraftOut, status_code=status.HTTP_201_CREATED)
async def generate_draft(
    file: UploadFile = File(...),
    request_key: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogAiService = Depends(get_catalog_ai_service),
    settings: Settings = Depends(get_settings),
) -> DraftOut:
    data = await file.read()
    draft = service.generate_draft(
        principal.business_id,
        image=data,
        content_type=file.content_type or "application/octet-stream",
        request_key=request_key or idempotency_key,
    )
    return _out(draft, settings)


@router.get("/drafts", response_model=list[DraftOut])
def list_drafts(
    principal: Principal = Depends(get_current_principal),
    service: CatalogAiService = Depends(get_catalog_ai_service),
    settings: Settings = Depends(get_settings),
) -> list[DraftOut]:
    return [_out(d, settings) for d in service.list_drafts(principal.business_id)]


@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_draft(
    draft_id: int,
    principal: Principal = Depends(get_current_principal),
    service: CatalogAiService = Depends(get_catalog_ai_service),
    settings: Settings = Depends(get_settings),
) -> DraftOut:
    return _out(service.get_draft(principal.business_id, draft_id), settings)


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def edit_draft(
    draft_id: int,
    payload: DraftEdit,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogAiService = Depends(get_catalog_ai_service),
    settings: Settings = Depends(get_settings),
) -> DraftOut:
    return _out(service.edit_draft(principal.business_id, draft_id, payload), settings)


@router.post("/drafts/{draft_id}/regenerate", response_model=DraftOut)
def regenerate_draft(
    draft_id: int,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogAiService = Depends(get_catalog_ai_service),
    settings: Settings = Depends(get_settings),
) -> DraftOut:
    return _out(service.regenerate(principal.business_id, draft_id), settings)


@router.post("/drafts/{draft_id}/reject", response_model=DraftOut)
def reject_draft(
    draft_id: int,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogAiService = Depends(get_catalog_ai_service),
    settings: Settings = Depends(get_settings),
) -> DraftOut:
    return _out(service.reject(principal.business_id, draft_id), settings)


@router.post(
    "/drafts/{draft_id}/approve",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
)
def approve_draft(
    draft_id: int,
    payload: DraftEdit | None = None,
    principal: Principal = Depends(require_role(*_MUTATOR_ROLES)),
    service: CatalogAiService = Depends(get_catalog_ai_service),
) -> ProductOut:
    product = service.approve(
        principal.business_id,
        draft_id,
        approver_user_id=principal.user_id,
        edit=payload,
    )
    return ProductOut.from_model(product)
