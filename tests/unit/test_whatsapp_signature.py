"""Unit tests for Meta webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac

from app.whatsapp.signature import is_enforced, verify_signature

_SECRET = "app-secret-value"
_BODY = b'{"object":"whatsapp_business_account"}'


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_accepted() -> None:
    assert verify_signature(_SECRET, _BODY, _sign(_SECRET, _BODY)) is True


def test_wrong_signature_rejected() -> None:
    assert verify_signature(_SECRET, _BODY, _sign("other-secret", _BODY)) is False


def test_tampered_body_rejected() -> None:
    header = _sign(_SECRET, _BODY)
    assert verify_signature(_SECRET, _BODY + b"tampered", header) is False


def test_missing_header_rejected_when_secret_set() -> None:
    assert verify_signature(_SECRET, _BODY, None) is False


def test_malformed_header_rejected() -> None:
    assert verify_signature(_SECRET, _BODY, "not-a-signature") is False


def test_no_secret_skips_verification() -> None:
    # Dev fallback: with no app secret configured, verification is not enforced.
    assert verify_signature("", _BODY, None) is True
    assert is_enforced("") is False
    assert is_enforced(_SECRET) is True
