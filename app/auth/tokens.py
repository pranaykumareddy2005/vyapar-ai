"""Refresh-token revocation store.

Logout and refresh-rotation revoke a refresh token by denylisting its ``jti``
until it would have expired anyway. The domain depends on the
:class:`RefreshTokenStore` protocol; the concrete backend (in-memory for
dev/test, Redis for multi-process/prod) is chosen by config.

Note: the in-memory backend is process-local and does not survive restarts or
span workers - acceptable for development, not for production (use Redis).
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

import redis

_REVOKE_PREFIX = "revoked_refresh:"


@runtime_checkable
class RefreshTokenStore(Protocol):
    def revoke(self, jti: str, ttl_seconds: int) -> None: ...

    def is_revoked(self, jti: str) -> bool: ...


class InMemoryRefreshTokenStore:
    """Process-local denylist keyed by jti with monotonic expiry."""

    def __init__(self) -> None:
        self._revoked: dict[str, float] = {}

    def _purge(self, now: float) -> None:
        expired = [jti for jti, exp in self._revoked.items() if exp <= now]
        for jti in expired:
            del self._revoked[jti]

    def revoke(self, jti: str, ttl_seconds: int) -> None:
        now = time.monotonic()
        self._purge(now)
        self._revoked[jti] = now + max(ttl_seconds, 0)

    def is_revoked(self, jti: str) -> bool:
        now = time.monotonic()
        exp = self._revoked.get(jti)
        if exp is None:
            return False
        if exp <= now:
            del self._revoked[jti]
            return False
        return True

    def clear(self) -> None:
        self._revoked.clear()


class RedisRefreshTokenStore:
    """Redis-backed denylist; entries auto-expire via key TTL."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def revoke(self, jti: str, ttl_seconds: int) -> None:
        self._client.set(_REVOKE_PREFIX + jti, "1", ex=max(ttl_seconds, 1))

    def is_revoked(self, jti: str) -> bool:
        return bool(self._client.exists(_REVOKE_PREFIX + jti))
