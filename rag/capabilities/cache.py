import hashlib
import json
import logging
from typing import Any, Callable

from rag.config import settings

logger = logging.getLogger(__name__)
_redis = None


def get_redis():
    """Public: return live Redis client, or None if unavailable."""
    global _redis
    if _redis is not None:
        return _redis
    if not settings.redis_url:
        return None
    try:
        import redis as _redis_lib
        r = _redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        _redis = r
        logger.info("Redis cache connected: %s", settings.redis_url)
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — cache disabled", exc)
        _redis = None
    return _redis


def read_cache(prefix: str, key: str) -> Any | None:
    """Read-only lookup: return cached value or None (never writes)."""
    r = get_redis() if _redis is None else _redis
    if r is None:
        return None
    hashed = hashlib.sha256(key.encode()).hexdigest()
    try:
        hit = r.get(f"{prefix}:{hashed}")
        return json.loads(hit) if hit is not None else None
    except Exception:
        return None


def cached(prefix: str, key: str, ttl: int, fn: Callable[[], Any]) -> Any:
    """Return cached value for key or call fn() and cache its result."""
    r = get_redis() if _redis is None else _redis
    if r is None:
        return fn()

    hashed = hashlib.sha256(key.encode()).hexdigest()
    cache_key = f"{prefix}:{hashed}"
    try:
        hit = r.get(cache_key)
        if hit is not None:
            return json.loads(hit)
        val = fn()
        r.setex(cache_key, ttl, json.dumps(val))
        return val
    except Exception as exc:
        logger.warning("Cache error (%s) — calling fn() directly", exc)
        return fn()
