"""Redis connection helper.

Redis backs caching, rate-limit counters, and hot lookups. The client is
created lazily so importing the module never forces a live connection (keeps
unit tests hermetic).
"""

from __future__ import annotations

from functools import lru_cache

import redis

from app.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Return the process-wide Redis client (lazy, connection-pooled)."""
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)
