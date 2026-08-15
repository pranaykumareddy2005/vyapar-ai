"""FastAPI wiring for the WhatsApp webhook + UX router + flows.

All collaborators share the *same* request-scoped session so the dedup claim,
session state, customer upsert, and every domain write (catalogue/order/payment/
invoice) commit atomically. The messaging provider is narrowed to the richer
:class:`WhatsAppChannel`; both the Meta provider and the test mock satisfy it.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth.repository import UserRepository
from app.business.repository import BusinessRepository
from app.catalog.dependencies import get_catalog_service
from app.catalog.service import CatalogService
from app.catalogai.dependencies import get_catalog_ai_service
from app.catalogai.service import CatalogAiService
from app.common.messaging import MessagingProvider
from app.conversation.dependencies import get_conversation_service
from app.conversation.service import ConversationService
from app.customer.dependencies import get_customer_service
from app.customer.service import CustomerService
from app.db import get_session
from app.inventory.dependencies import get_inventory_service
from app.inventory.service import InventoryService
from app.invoice.dependencies import get_invoice_service
from app.invoice.service import InvoiceService
from app.order.dependencies import get_order_service
from app.order.service import OrderService
from app.payment.dependencies import get_payment_service
from app.payment.service import PaymentService
from app.providers import get_messaging_provider
from app.whatsapp.channel import WhatsAppChannel
from app.whatsapp.repository import (
    WebhookEventRepository,
    WhatsAppSessionRepository,
    WhatsAppStaffRepository,
)
from app.whatsapp.seller_flow import SellerFlow
from app.whatsapp.service import WhatsAppWebhookService
from app.whatsapp.shop_flow import ShopFlow


def get_webhook_service(
    session: Session = Depends(get_session),
    conversation: ConversationService = Depends(get_conversation_service),
    customers: CustomerService = Depends(get_customer_service),
    catalog: CatalogService = Depends(get_catalog_service),
    inventory: InventoryService = Depends(get_inventory_service),
    catalog_ai: CatalogAiService = Depends(get_catalog_ai_service),
    orders: OrderService = Depends(get_order_service),
    payments: PaymentService = Depends(get_payment_service),
    invoices: InvoiceService = Depends(get_invoice_service),
    messaging: MessagingProvider = Depends(get_messaging_provider),
) -> WhatsAppWebhookService:
    if not isinstance(messaging, WhatsAppChannel):
        raise RuntimeError("configured messaging provider is not a WhatsApp channel")
    staff = WhatsAppStaffRepository(session)
    seller = SellerFlow(catalog_ai, UserRepository(session), staff)
    shop = ShopFlow(catalog, inventory, customers, orders, payments, invoices)
    return WhatsAppWebhookService(
        session,
        BusinessRepository(session),
        WebhookEventRepository(session),
        WhatsAppSessionRepository(session),
        staff,
        customers,
        conversation,
        messaging,
        seller,
        shop,
    )
