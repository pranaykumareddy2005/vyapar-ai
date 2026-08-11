"""FastAPI wiring for the conversation service.

Composes the conversation AI provider, the messaging boundary, and the existing
Catalog/Inventory application services (reused, not re-implemented).
"""

from __future__ import annotations

from fastapi import Depends

from app.catalog.dependencies import get_catalog_service
from app.catalog.service import CatalogService
from app.common.messaging import MessagingProvider
from app.config import Settings, get_settings
from app.conversation.provider import ConversationAiProvider
from app.conversation.service import ConversationService
from app.inventory.dependencies import get_inventory_service
from app.inventory.service import InventoryService
from app.providers import get_conversation_ai_provider, get_messaging_provider


def get_conversation_service(
    provider: ConversationAiProvider = Depends(get_conversation_ai_provider),
    messaging: MessagingProvider = Depends(get_messaging_provider),
    catalog: CatalogService = Depends(get_catalog_service),
    inventory: InventoryService = Depends(get_inventory_service),
    settings: Settings = Depends(get_settings),
) -> ConversationService:
    return ConversationService(
        provider,
        messaging,
        catalog,
        inventory,
        confidence_threshold=settings.ai_confidence_threshold,
    )
