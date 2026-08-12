"""Application configuration.

All configuration is sourced from the environment (or a local ``.env`` file);
secrets are never hard-coded. Access the singleton via :func:`get_settings`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -----------------------------------------------------------
    environment: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "Vyapar AI"
    debug: bool = False

    # --- Datastores --------------------------------------------------------
    db_url: str = "postgresql+psycopg://vyapar:vyapar@localhost:5432/vyapar"
    redis_url: str = "redis://localhost:6379/0"

    # --- Security ----------------------------------------------------------
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 14

    # --- Messaging (WhatsApp) ---------------------------------------------
    # "mock" wires MockMessagingProvider. "whatsapp" is reserved for a future
    # WhatsApp/Meta adapter and is not yet implemented (selecting it raises).
    messaging_provider: Literal["mock", "whatsapp"] = "mock"
    wa_verify_token: str = "dev-verify-token"
    wa_api_token: str = ""
    wa_phone_number_id: str = ""

    # --- AI provider ------------------------------------------------------
    ai_api_key: str = ""
    # Configurable confidence threshold. 0.6 is only a development default, not a
    # fixed business rule; below this the engine must ask for clarification.
    ai_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # "mock" wires the deterministic MockAiProvider (dev/test); "gemini" wires the
    # real GeminiAdapter, which requires AI_API_KEY. Never a silent fallback: the
    # provider is chosen explicitly.
    ai_provider: Literal["mock", "gemini"] = "mock"
    ai_model: str = "gemini-1.5-flash"
    ai_request_timeout_seconds: float = Field(default=30.0, gt=0.0)

    # --- Payments ---------------------------------------------------------
    # "mock" wires the deterministic MockPaymentProvider (dev/test); "razorpay"
    # wires RazorpayAdapter, which requires RZP_KEY/RZP_SECRET. Chosen explicitly;
    # never a silent fallback to the mock in production.
    payment_provider: Literal["mock", "razorpay"] = "mock"
    rzp_key: str = ""
    rzp_secret: str = ""
    rzp_api_base: str = "https://api.razorpay.com/v1"
    payment_request_timeout_seconds: float = Field(default=30.0, gt=0.0)
    # Trusted expected currency for payments; never taken from client input.
    default_currency: str = "INR"

    # --- Tax (configurable rate; NOT a hard-coded GST rule) ---------------
    default_tax_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # --- Notifications & analytics ----------------------------------------
    # In-app notifications are created post-commit from domain events. The global
    # event listener is disabled in the test environment so the rolled-back test
    # session is not touched by an independent-session listener.
    notifications_enabled: bool = True
    # Business timezone used to compute "today"/"this month" analytics boundaries;
    # boundaries are converted to a UTC created_at range (no UTC/local mixing).
    business_timezone: str = "UTC"

    # --- Object storage ----------------------------------------------------
    # "memory" uses the in-process fake (dev/test); "s3" targets MinIO/S3.
    storage_backend: Literal["memory", "s3"] = "memory"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "vyapar"
    s3_region: str = "us-east-1"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
