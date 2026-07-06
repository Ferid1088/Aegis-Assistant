"""Caps how many ingestion jobs a single user can have QUEUED at once -- distinct
from Celery's own worker concurrency (which caps how many run SIMULTANEOUSLY).
Uses a plain Redis INCR/DECR counter, keyed per user.
"""

import redis

from rag.config import settings

_redis_client = redis.Redis.from_url(settings.redis_url) if settings.redis_url else None


def _key(user_id: str) -> str:
    return f"ingestion_queued:{user_id}"


def check_and_increment_queued_ingestion(user_id: str, max_queued: int = 5) -> bool:
    if _redis_client is None:
        return True
    count = _redis_client.incr(_key(user_id))
    if count > max_queued:
        _redis_client.decr(_key(user_id))
        return False
    return True


def decrement_queued_ingestion(user_id: str) -> None:
    if _redis_client is None:
        return
    _redis_client.decr(_key(user_id))
