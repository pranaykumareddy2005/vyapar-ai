"""Unit tests for the Meta WhatsApp provider (mocked HTTP transport)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from app.common.messaging import OutgoingMessage
from app.whatsapp.provider import (
    MetaWhatsAppConfigError,
    MetaWhatsAppInvalidRecipient,
    MetaWhatsAppInvalidResponse,
    MetaWhatsAppProvider,
    MetaWhatsAppRateLimited,
    MetaWhatsAppTimeout,
    MetaWhatsAppUnavailable,
)

_TOKEN = "EAA-secret-token-value"


def _provider(
    handler: Callable[[httpx.Request], httpx.Response], *, max_retries: int = 3
) -> MetaWhatsAppProvider:
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    return MetaWhatsAppProvider(
        access_token=_TOKEN,
        phone_number_id="PNID",
        client=client,
        max_retries=max_retries,
        sleep=lambda _s: None,  # no real backoff sleeps in tests
    )


def _msg(text: str = "hello") -> OutgoingMessage:
    return OutgoingMessage(business_id=1, recipient_phone="919111111111", text=text)


def test_send_text_success() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.OUT1"}]})

    result = _provider(handler).send(_msg("Notebook has 27 units."))
    assert result.provider_message_id == "wamid.OUT1"
    assert result.accepted is True
    assert seen["path"] == "/v21.0/PNID/messages"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["to"] == "919111111111"
    assert body["type"] == "text"
    assert body["text"]["body"] == "Notebook has 27 units."
    assert body["messaging_product"] == "whatsapp"


def test_send_template_message() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.T"}]})

    out = OutgoingMessage(
        business_id=1, recipient_phone="919111111111", text="", template_name="order_update"
    )
    assert _provider(handler).send(out).provider_message_id == "wamid.T"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["type"] == "template"
    assert body["template"]["name"] == "order_update"


def test_auth_header_wired_from_token() -> None:
    # The provider builds its own client and attaches the bearer token.
    provider = MetaWhatsAppProvider(access_token=_TOKEN, phone_number_id="PNID")
    assert provider._client.headers["authorization"] == f"Bearer {_TOKEN}"


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, MetaWhatsAppConfigError),
        (403, MetaWhatsAppConfigError),
        (429, MetaWhatsAppRateLimited),
        (400, MetaWhatsAppInvalidRecipient),
        (500, MetaWhatsAppUnavailable),
        (503, MetaWhatsAppUnavailable),
    ],
)
def test_http_errors_mapped(status: int, exc: type[Exception]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "meta error detail"}})

    with pytest.raises(exc) as caught:
        _provider(handler).send(_msg())
    # The access token must never appear in a raised error message.
    assert _TOKEN not in str(caught.value)


def test_timeout_mapped() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(MetaWhatsAppTimeout):
        _provider(handler).send(_msg())


def test_transport_error_mapped_to_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(MetaWhatsAppUnavailable):
        _provider(handler).send(_msg())


def test_non_json_response_is_invalid() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(MetaWhatsAppInvalidResponse):
        _provider(handler).send(_msg())


def test_missing_message_id_is_invalid() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": []})

    with pytest.raises(MetaWhatsAppInvalidResponse):
        _provider(handler).send(_msg())


def test_upload_media_returns_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v21.0/PNID/media"
        return httpx.Response(200, json={"id": "MEDIA999"})

    assert (
        _provider(handler).upload_media(b"pdfbytes", filename="i.pdf", mime_type="application/pdf")
        == "MEDIA999"
    )


def test_upload_media_missing_id_invalid() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(MetaWhatsAppInvalidResponse):
        _provider(handler).upload_media(b"x", filename="i.pdf", mime_type="application/pdf")


def test_download_media_returns_bytes_and_mime() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/MID"):
            return httpx.Response(
                200, json={"url": "https://media.example/x", "mime_type": "image/png"}
            )
        return httpx.Response(200, content=b"\x89PNG-bytes")

    data, mime = _provider(handler).download_media("MID")
    assert data == b"\x89PNG-bytes"
    assert mime == "image/png"


def test_send_document_success() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.doc"}]})

    result = _provider(handler).send_document(
        "919111111111", media_id="MID", filename="invoice.pdf", caption="Your invoice"
    )
    assert result.provider_message_id == "wamid.doc"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["type"] == "document"
    assert body["document"]["id"] == "MID"
    assert body["document"]["filename"] == "invoice.pdf"
    assert body["document"]["caption"] == "Your invoice"


def test_send_image_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["type"] == "image"
        assert body["image"]["id"] == "IMG1"
        return httpx.Response(200, json={"messages": [{"id": "wamid.img"}]})

    assert (
        _provider(handler).send_image("919111111111", media_id="IMG1").provider_message_id
        == "wamid.img"
    )


def test_send_buttons_payload() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.btn"}]})

    result = _provider(handler).send_buttons(
        "919111111111",
        body="Pick one",
        buttons=[("menu:browse", "🛍️ Browse"), ("menu:search", "🔎 Search")],
    )
    assert result.provider_message_id == "wamid.btn"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["type"] == "interactive"
    interactive = body["interactive"]
    assert interactive["type"] == "button"
    ids = [b["reply"]["id"] for b in interactive["action"]["buttons"]]
    assert ids == ["menu:browse", "menu:search"]


def test_send_buttons_caps_at_three() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert len(body["interactive"]["action"]["buttons"]) == 3
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    _provider(handler).send_buttons(
        "919111111111",
        body="Many",
        buttons=[(f"id:{i}", f"t{i}") for i in range(5)],
    )


def test_send_list_payload() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.list"}]})

    _provider(handler).send_list(
        "919111111111",
        body="Products",
        button_text="View",
        rows=[("prod:1", "Notebook", "₹50"), ("prod:2", "Pen", "₹10")],
    )
    body = seen["body"]
    assert isinstance(body, dict)
    interactive = body["interactive"]
    assert interactive["type"] == "list"
    rows = interactive["action"]["sections"][0]["rows"]
    assert [r["id"] for r in rows] == ["prod:1", "prod:2"]


def test_mark_read_success_and_failure() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["status"] == "read"
        assert body["message_id"] == "wamid.in"
        return httpx.Response(200, json={"success": True})

    assert _provider(ok).mark_read("wamid.in") is True

    def fail(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad"}})

    # mark_read never raises - a failed receipt must not break handling.
    assert _provider(fail).mark_read("wamid.in") is False


def test_retry_recovers_after_transient_5xx() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.retry"}]})

    result = _provider(handler).send(_msg())
    assert result.provider_message_id == "wamid.retry"
    assert calls["n"] == 3  # two transient failures, then success


def test_retry_exhausted_raises_unavailable() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    with pytest.raises(MetaWhatsAppUnavailable):
        _provider(handler).send(_msg())
    assert calls["n"] == 3  # bounded by max_retries


def test_definitive_4xx_not_retried() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"message": "bad recipient"}})

    with pytest.raises(MetaWhatsAppInvalidRecipient):
        _provider(handler).send(_msg())
    assert calls["n"] == 1  # 400 is not retried


def test_missing_credentials_rejected() -> None:
    with pytest.raises(MetaWhatsAppConfigError):
        MetaWhatsAppProvider(access_token="", phone_number_id="PNID")
    with pytest.raises(MetaWhatsAppConfigError):
        MetaWhatsAppProvider(access_token="tok", phone_number_id="")


def test_empty_recipient_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    with pytest.raises(MetaWhatsAppInvalidRecipient):
        _provider(handler).send(OutgoingMessage(business_id=1, recipient_phone="", text="hi"))
