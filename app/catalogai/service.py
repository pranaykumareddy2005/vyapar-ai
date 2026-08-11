"""AI Catalog Generator application service.

Orchestrates: image -> multimodal draft -> merchant review/edit -> explicit
approval -> ``CatalogService.create_product``. The human-in-the-loop gate is
structural: a ``Product`` is created **only** in :meth:`approve`, never as a side
effect of generation (FR-CATAI-03..05, plan item 6).

Tenant scoping is by an explicit ``business_id`` from the authenticated principal.
Provider failures are recorded as a durable ``FAILED`` draft and re-raised as a
domain error - never silently treated as success (plan item 11).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalog.models import Product
from app.catalog.schemas import ProductCreate
from app.catalog.service import CatalogService
from app.catalogai.models import (
    APPROVABLE_FROM,
    REGENERATABLE_FROM,
    TERMINAL,
    CatalogAiDraft,
    DraftStatus,
)
from app.catalogai.provider import AiGenerationError, AiProvider, AiProviderError
from app.catalogai.repository import CatalogAiDraftRepository
from app.catalogai.schemas import AiDraftPayload, DraftEdit
from app.common.exceptions import ConflictError, NotFoundError, ValidationError
from app.common.storage import ObjectStorage

_ALLOWED_IMAGE_PREFIX = "image/"


class CatalogAiService:
    def __init__(
        self,
        session: Session,
        drafts: CatalogAiDraftRepository,
        catalog: CatalogService,
        provider: AiProvider,
        storage: ObjectStorage,
    ) -> None:
        self._session = session
        self._drafts = drafts
        self._catalog = catalog
        self._provider = provider
        self._storage = storage

    # --- generation -------------------------------------------------------

    def generate_draft(
        self,
        business_id: int,
        *,
        image: bytes,
        content_type: str,
        request_key: str | None = None,
    ) -> CatalogAiDraft:
        """Store the image, call the provider, and persist a draft.

        No ``Product`` is created here. On provider failure the draft is saved in
        the ``FAILED`` state and :class:`AiGenerationError` is raised.
        """
        if not content_type.startswith(_ALLOWED_IMAGE_PREFIX):
            raise ValidationError("only image content types are supported")
        if not image:
            raise ValidationError("empty image payload")

        # Idempotency: a repeated request with the same key returns the same draft
        # rather than generating (and later approving) a duplicate (plan item 18).
        if request_key is not None:
            existing = self._drafts.get_by_request_key(business_id, request_key)
            if existing is not None:
                return existing

        key = f"{business_id}/catalog-ai/{uuid.uuid4().hex}"
        url = self._storage.put(key, image, content_type)

        draft = self._drafts.add(
            CatalogAiDraft(
                business_id=business_id,
                status=DraftStatus.PENDING,
                source_storage_key=key,
                source_image_url=url,
                source_content_type=content_type,
                ai_provider=self._provider.name,
                ai_model=self._provider.model,
                request_key=request_key,
            )
        )
        self._commit()
        return self._run_generation(business_id, draft, image, content_type)

    def regenerate(self, business_id: int, draft_id: int) -> CatalogAiDraft:
        """Re-run the provider on a draft's stored image (retry a FAILED draft)."""
        draft = self._require(business_id, draft_id)
        if draft.status not in REGENERATABLE_FROM:
            raise ConflictError(f"draft cannot be regenerated from state {draft.status.value}")
        if not draft.source_storage_key:
            raise ValidationError("draft has no source image to regenerate from")
        image = self._storage.get(draft.source_storage_key)
        content_type = draft.source_content_type or "image/jpeg"
        return self._run_generation(business_id, draft, image, content_type)

    def _run_generation(
        self,
        business_id: int,
        draft: CatalogAiDraft,
        image: bytes,
        content_type: str,
    ) -> CatalogAiDraft:
        try:
            payload = self._provider.describe(image, content_type)
        except AiProviderError as exc:
            draft.status = DraftStatus.FAILED
            draft.error_code = exc.code
            draft.error_detail = str(exc)[:2000]
            self._commit()
            raise AiGenerationError(
                "AI generation failed; the draft was saved and can be retried"
            ) from exc

        self._apply_payload(business_id, draft, payload)
        draft.status = DraftStatus.GENERATED
        draft.error_code = None
        draft.error_detail = None
        self._commit()
        self._session.refresh(draft)
        return draft

    def _apply_payload(
        self, business_id: int, draft: CatalogAiDraft, payload: AiDraftPayload
    ) -> None:
        draft.name = payload.name
        draft.description = payload.description
        draft.sku_suggestion = payload.sku_suggestion
        draft.tags = payload.tags
        draft.confidence = payload.confidence
        draft.category_suggestion = payload.category_suggestion
        # Match the suggested category name against the business's existing
        # categories (case-insensitive). Never auto-create one (plan item 13).
        draft.category_id = self._match_category(business_id, payload.category_suggestion)
        # Price is never populated from the model; it remains merchant-supplied.

    def _match_category(self, business_id: int, suggestion: str | None) -> int | None:
        if not suggestion:
            return None
        wanted = suggestion.strip().casefold()
        for category in self._catalog.list_categories(business_id):
            if category.name.strip().casefold() == wanted:
                return category.id
        return None

    # --- review / edit ----------------------------------------------------

    def get_draft(self, business_id: int, draft_id: int) -> CatalogAiDraft:
        return self._require(business_id, draft_id)

    def list_drafts(self, business_id: int) -> list[CatalogAiDraft]:
        return self._drafts.list(business_id)

    def edit_draft(self, business_id: int, draft_id: int, edit: DraftEdit) -> CatalogAiDraft:
        draft = self._require(business_id, draft_id)
        if draft.status in TERMINAL:
            raise ConflictError(f"a {draft.status.value} draft cannot be edited")
        self._apply_edit(business_id, draft, edit)
        self._commit()
        self._session.refresh(draft)
        return draft

    def _apply_edit(self, business_id: int, draft: CatalogAiDraft, edit: DraftEdit) -> None:
        data = edit.model_dump(exclude_unset=True)
        if "category_id" in data:
            self._validate_category(business_id, data["category_id"])
            draft.category_id = data["category_id"]
        if "name" in data:
            draft.name = data["name"]
        if "description" in data:
            draft.description = data["description"]
        if "sku" in data:
            draft.sku_suggestion = data["sku"]
        if "price" in data:
            draft.price_amt = data["price"]

    def _validate_category(self, business_id: int, category_id: int | None) -> None:
        if category_id is None:
            return
        owned = any(c.id == category_id for c in self._catalog.list_categories(business_id))
        if not owned:
            raise ValidationError("category does not exist for this business")

    # --- approval / rejection --------------------------------------------

    def approve(
        self,
        business_id: int,
        draft_id: int,
        *,
        approver_user_id: int,
        edit: DraftEdit | None = None,
    ) -> Product:
        """Create the final ``Product`` via ``CatalogService`` - the only path to a
        product. Idempotent: re-approving returns the already-created product.
        """
        draft = self._require(business_id, draft_id)

        # Idempotency: an already-approved draft returns its product; no duplicate.
        if draft.status == DraftStatus.APPROVED and draft.approved_product_id is not None:
            return self._catalog.get_product(business_id, draft.approved_product_id)

        if draft.status not in APPROVABLE_FROM:
            raise ConflictError(f"draft cannot be approved from state {draft.status.value}")

        if edit is not None:
            self._apply_edit(business_id, draft, edit)
            self._session.flush()

        payload = self._build_product_create(draft)
        # CatalogService owns product validation, SKU uniqueness and the commit.
        product = self._catalog.create_product(business_id, payload)

        draft.status = DraftStatus.APPROVED
        draft.approved_product_id = product.id
        draft.approved_by = approver_user_id
        draft.approved_at = datetime.now(UTC)
        self._commit()
        return product

    def reject(self, business_id: int, draft_id: int) -> CatalogAiDraft:
        draft = self._require(business_id, draft_id)
        if draft.status in TERMINAL:
            raise ConflictError(f"a {draft.status.value} draft cannot be rejected")
        draft.status = DraftStatus.REJECTED
        self._commit()
        self._session.refresh(draft)
        return draft

    def _build_product_create(self, draft: CatalogAiDraft) -> ProductCreate:
        name = (draft.name or "").strip()
        sku = (draft.sku_suggestion or "").strip()
        price: Decimal | None = draft.price_amt
        if not name:
            raise ValidationError("product name is required before approval")
        if not sku:
            raise ValidationError("sku is required before approval")
        if price is None:
            raise ValidationError("price must be set by the merchant before approval")
        return ProductCreate(
            name=name,
            price=price,
            sku=sku,
            category_id=draft.category_id,
            description=draft.description,
        )

    # --- helpers ----------------------------------------------------------

    def _require(self, business_id: int, draft_id: int) -> CatalogAiDraft:
        draft = self._drafts.get(business_id, draft_id)
        if draft is None:
            raise NotFoundError("draft not found")
        return draft

    def _commit(self) -> None:
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
