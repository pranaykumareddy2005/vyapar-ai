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
    """Select the messaging provider from configuration."""
    if settings.messaging_provider == "whatsapp":
        # WhatsAppMessagingProvider is implemented in Phase 5. Fail loudly
        # rather than silently degrading to the mock in a real environment.
        raise NotImplementedError(
            "WhatsAppMessagingProvider is not available until Phase 5; "
            "set MESSAGING_PROVIDER=mock for development."
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
    mock in production (plan item 20). ``gemini`` requires ``AI_API_KEY`` and
    fails loudly if it is missing.
    """
    if settings.ai_provider == "gemini":
        # Imported lazily so the mock path never imports the vendor adapter.
        from app.catalogai.adapters.gemini import GeminiAdapter

        return GeminiAdapter(
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout=settings.ai_request_timeout_seconds,
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
