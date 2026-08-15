from __future__ import annotations

import pytest
from app.common.messaging import (
    IncomingMessage,
    MessageType,
    MessagingProvider,
    MockMessagingProvider,
    OutgoingMessage,
)
from app.config import Settings
from app.providers import build_messaging_provider


def test_mock_provider_records_and_returns_id() -> None:
    provider = MockMessagingProvider()
    result = provider.send(OutgoingMessage(business_id=1, recipient_phone="+9100", text="hi"))
    assert result.accepted
    assert result.provider_message_id == "mock-1"
    assert provider.last_to("+9100") is not None


def test_mock_provider_satisfies_protocol() -> None:
    assert isinstance(MockMessagingProvider(), MessagingProvider)


def test_incoming_message_is_vendor_neutral() -> None:
    msg = IncomingMessage(
        business_id=1,
        sender_phone="+9199",
        message_id="abc",
        message_type=MessageType.TEXT,
        text="add 10 notebooks",
    )
    assert msg.message_type is MessageType.TEXT
    assert msg.text == "add 10 notebooks"


def test_build_mock_provider_from_settings() -> None:
    provider = build_messaging_provider(Settings(messaging_provider="mock"))
    assert isinstance(provider, MockMessagingProvider)


def test_meta_provider_built_from_settings() -> None:
    # "meta" (and its alias "whatsapp") wire the real Meta adapter when credentials
    # are present; both resolve to a MessagingProvider.
    from app.whatsapp.provider import MetaWhatsAppProvider

    for selector in ("meta", "whatsapp"):
        provider = build_messaging_provider(
            Settings(
                messaging_provider=selector,  # type: ignore[arg-type]
                wa_api_token="test-token",
                wa_phone_number_id="PNID",
            )
        )
        assert isinstance(provider, MetaWhatsAppProvider)
        assert isinstance(provider, MessagingProvider)


def test_meta_provider_requires_credentials() -> None:
    from app.whatsapp.provider import MetaWhatsAppConfigError

    with pytest.raises(MetaWhatsAppConfigError):
        build_messaging_provider(Settings(messaging_provider="meta", wa_api_token=""))


def test_mock_rejected_in_production() -> None:
    with pytest.raises(NotImplementedError, match="not permitted in production"):
        build_messaging_provider(Settings(environment="production", messaging_provider="mock"))
