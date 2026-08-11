"""AI provider abstraction for the catalog generator.

The domain/application layer depends only on the :class:`AiProvider` Protocol,
never on a vendor SDK (Adapter pattern, LLD §2.3 / Impl §5.4). Concrete adapters
(:class:`MockAiProvider`, ``GeminiAdapter``) are selected by configuration in the
composition root and are freely replaceable.

Provider failures are modelled as an explicit exception hierarchy so the service
can record a durable failure state instead of ever treating a failed call as a
successful generation (plan item 11).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.catalogai.schemas import AiDraftPayload
from app.common.exceptions import DomainError


class AiProviderError(Exception):
    """Base class for all AI-provider failures (infrastructure, not domain)."""

    code = "ai_provider_error"


class AiProviderTimeout(AiProviderError):
    code = "ai_provider_timeout"


class AiProviderUnavailable(AiProviderError):
    code = "ai_provider_unavailable"


class AiProviderRateLimited(AiProviderError):
    code = "ai_provider_rate_limited"


class AiProviderConfigError(AiProviderError):
    """Missing/invalid credentials or provider configuration."""

    code = "ai_provider_config_error"


class AiInvalidResponse(AiProviderError):
    """The provider returned an empty, malformed, or schema-invalid response."""

    code = "ai_invalid_response"


class AiGenerationError(DomainError):
    """Domain-level error surfaced to the API when generation cannot complete.

    Maps to HTTP 502; the underlying draft is persisted in the ``FAILED`` state so
    the merchant can retry.
    """

    status_code = 502
    code = "ai_generation_failed"


@runtime_checkable
class AiProvider(Protocol):
    """Vision + language boundary: image -> validated structured listing.

    Implementations MUST raise an :class:`AiProviderError` subclass on any failure
    and MUST NOT return a price (a price is never inferred from an image).
    """

    name: str
    model: str

    def describe(self, image: bytes, content_type: str) -> AiDraftPayload:
        """Return a validated draft listing for ``image`` (no price, ever)."""
        ...


class MockAiProvider:
    """Deterministic provider for development and tests.

    Returns fixed, predictable data (never random) so tests are reproducible while
    exercising the exact :class:`AiProvider` interface the real adapter implements.
    The suggested category defaults to ``"Groceries"`` so category-matching can be
    exercised end to end.
    """

    name = "mock"

    def __init__(
        self,
        *,
        model: str = "mock-1",
        confidence: float = 0.9,
        category_suggestion: str = "Groceries",
    ) -> None:
        self.model = model
        self._confidence = confidence
        self._category = category_suggestion

    def describe(self, image: bytes, content_type: str) -> AiDraftPayload:
        if not image:
            # Mirrors a real adapter rejecting an empty upload.
            raise AiInvalidResponse("empty image payload")
        return AiDraftPayload(
            name="Sample Product",
            description="A clear, concise product description drafted from the photo.",
            category_suggestion=self._category,
            sku_suggestion="AI-SKU-0001",
            tags=["sample", "ai-generated"],
            confidence=self._confidence,
        )
