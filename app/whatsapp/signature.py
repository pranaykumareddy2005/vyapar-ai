"""Meta webhook payload authentication (``X-Hub-Signature-256``).

Meta signs each webhook POST with HMAC-SHA256 of the raw request body using the
app secret. Verifying it proves the request really came from Meta. When no app
secret is configured (dev), verification is skipped by policy - the caller decides
whether to enforce. The comparison is constant-time.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(app_secret: str, raw_body: bytes, header_value: str | None) -> bool:
    """Return ``True`` iff ``header_value`` is a valid signature for ``raw_body``.

    ``header_value`` is the ``X-Hub-Signature-256`` header, formatted
    ``sha256=<hexdigest>``. A missing/malformed header is invalid.
    """
    if not app_secret:
        # No secret configured: signature enforcement is disabled (dev fallback).
        return True
    if not header_value or not header_value.startswith("sha256="):
        return False
    provided = header_value.split("=", 1)[1]
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def is_enforced(app_secret: str) -> bool:
    """Whether signature verification is actually enforced (secret present)."""
    return bool(app_secret)
