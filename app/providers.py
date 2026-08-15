"""Composition root for infrastructure adapters.

Central place that constructs the messaging and storage providers from config
and exposes them as FastAPI-injectable singletons. Keeping construction here
means domain modules depend on abstractions only and never choose a concrete
vendor themselves.
"""

from __future__ import annotations

from functools import lru_cache

from app.auth.tokens import (
    InMemoryRefreshTokenStore,
    RedisRefreshTokenStore,
    RefreshTokenStore,
)
from app.catalogai.provider import AiProvider, AiProviderConfigError, MockAiProvider
from app.common.messaging import MessagingProvider, MockMessagingProvider
from app.common.storage import ObjectStorage, build_storage
from app.config import Settings, get_settings
from app.conversation.provider import (
    ConversationAiConfigError,
    ConversationAiProvider,
    MockConversationAiProvider,
)
from app.payment.provider import (
    MockPaymentProvider,
    PaymentProvider,
    PaymentProviderConfigError,
)
from app.redis_client import get_redis


def build_messaging_provider(settings: Settings) -> MessagingProvider:
    """Select the messaging provider from configuration (Adapter/Factory).

    ``meta`` (alias ``whatsapp``) wires the real Meta WhatsApp Cloud API adapter,
    which requires WA_API_TOKEN + WA_PHONE_NUMBER_ID and fails loudly if missing.
    Chosen explicitly; never a silent fallback to the mock in production.
    """
    if settings.messaging_provider in ("meta", "whatsapp"):
        # Imported lazily so the mock path never imports the vendor adapter.
        from app.whatsapp.provider import MetaWhatsAppProvider

        return MetaWhatsAppProvider(
            access_token=settings.wa_api_token,
            phone_number_id=settings.wa_phone_number_id,
            api_base=settings.wa_api_base,
            api_version=settings.wa_api_version,
            timeout=settings.wa_request_timeout_seconds,
        )
    if settings.is_production:
        raise NotImplementedError(
            "MESSAGING_PROVIDER=mock is not permitted in production; set MESSAGING_PROVIDER=meta."
        )
    return MockMessagingProvider()


@lru_cache(maxsize=1)
def get_messaging_provider() -> MessagingProvider:
    """Process-wide messaging provider (FastAPI dependency)."""
    return build_messaging_provider(get_settings())


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    """Process-wide object storage (FastAPI dependency)."""
    return build_storage(get_settings())


def build_ai_provider(settings: Settings) -> AiProvider:
    """Select the AI provider from configuration (Adapter/Factory patterns).

    The provider is chosen explicitly; there is never a silent fallback to the
    mock in production. ``gemini`` requires ``AI_API_KEY`` and fails loudly if it
    is missing.
    """
    if settings.ai_provider == "gemini":
        # Imported lazily so the mock path never imports the vendor adapter.
        from app.catalogai.adapters.gemini import GeminiAdapter

        return GeminiAdapter(
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout=settings.ai_request_timeout_seconds,
        )
    if settings.ai_provider == "ollama":
        from app.catalogai.adapters.ollama import OllamaAdapter

        return OllamaAdapter(
            base_url=settings.ollama_base_url,
            model=settings.ollama_catalog_model,
            timeout=settings.ollama_request_timeout_seconds,
        )
    if settings.is_production:
        raise AiProviderConfigError(
            "AI_PROVIDER=mock is not permitted in production; set AI_PROVIDER=gemini"
        )
    return MockAiProvider()


@lru_cache(maxsize=1)
def get_ai_provider() -> AiProvider:
    """Process-wide AI provider (FastAPI dependency)."""
    return build_ai_provider(get_settings())


def build_conversation_ai_provider(settings: Settings) -> ConversationAiProvider:
    """Select the conversation AI provider from configuration.

    Chosen explicitly; never a silent fallback to the mock in production.
    ``gemini`` requires ``AI_API_KEY`` and fails loudly if it is missing.
    """
    if settings.ai_provider == "gemini":
        from app.conversation.adapters.gemini import GeminiConversationAdapter

        return GeminiConversationAdapter(
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout=settings.ai_request_timeout_seconds,
        )
    if settings.ai_provider == "ollama":
        from app.conversation.adapters.ollama import OllamaConversationAdapter

        return OllamaConversationAdapter(
            base_url=settings.ollama_base_url,
            model=settings.ollama_conversation_model,
            timeout=settings.ollama_request_timeout_seconds,
        )
    if settings.is_production:
        raise ConversationAiConfigError(
            "AI_PROVIDER=mock is not permitted in production; set AI_PROVIDER=gemini"
        )
    return MockConversationAiProvider()


@lru_cache(maxsize=1)
def get_conversation_ai_provider() -> ConversationAiProvider:
    """Process-wide conversation AI provider (FastAPI dependency)."""
    return build_conversation_ai_provider(get_settings())


def build_payment_provider(settings: Settings) -> PaymentProvider:
    """Select the payment provider (gateway) from configuration.

    Chosen explicitly; never a silent fallback to the mock in production.
    ``razorpay`` requires RZP_KEY/RZP_SECRET and fails loudly if they are missing.
    """
    if settings.payment_provider == "razorpay":
        from app.payment.adapters.razorpay import RazorpayAdapter

        return RazorpayAdapter(
            key=settings.rzp_key,
            secret=settings.rzp_secret,
            api_base=settings.rzp_api_base,
            timeout=settings.payment_request_timeout_seconds,
        )
    if settings.is_production:
        raise PaymentProviderConfigError(
            "PAYMENT_PROVIDER=mock is not permitted in production; set PAYMENT_PROVIDER=razorpay"
        )
    return MockPaymentProvider()


@lru_cache(maxsize=1)
def get_payment_provider() -> PaymentProvider:
    """Process-wide payment provider (FastAPI dependency)."""
    return build_payment_provider(get_settings())


@lru_cache(maxsize=1)
def get_refresh_token_store() -> RefreshTokenStore:
    """Process-wide refresh-token revocation store (FastAPI dependency).

    Redis-backed outside development so revocations are shared across workers
    and survive restarts; in-memory otherwise.
    """
    settings = get_settings()
    if settings.environment in {"staging", "production"}:
        return RedisRefreshTokenStore(get_redis())
    return InMemoryRefreshTokenStore()
