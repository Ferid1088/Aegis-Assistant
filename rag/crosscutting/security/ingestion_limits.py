"""Caps how many ingestion jobs a single user can have QUEUED at once -- distinct
from Celery's own worker concurrency (which caps how many run SIMULTANEOUSLY).
Uses a plain Redis INCR/DECR counter, keyed per user.
"""

import redis

from rag.config import settings

_redis_client = redis.Redis.from_url(settings.redis_url) if settings.redis_url else None

# Backstop TTL for the per-user queued-ingestion counter. Every decrement path
# (task_postrun, or the upload endpoint's own failure handling) should already
# bring the counter back down, but this expiry self-heals any counter that gets
# orphaned by a decrement path nobody anticipated -- 6 hours is comfortably
# longer than any real ingestion job (including retries with backoff) should
# ever stay queued/running, so it never fires out from under a legitimate job.
_COUNTER_TTL_SECONDS = 6 * 60 * 60


def _key(user_id: str) -> str:
    return f"ingestion_queued:{user_id}"


def check_and_increment_queued_ingestion(user_id: str, max_queued: int = 5) -> bool:
    if _redis_client is None:
        return True
    count = _redis_client.incr(_key(user_id))
    _redis_client.expire(_key(user_id), _COUNTER_TTL_SECONDS)
    if count > max_queued:
        _redis_client.decr(_key(user_id))
        return False
    return True


def decrement_queued_ingestion(user_id: str) -> None:
    if _redis_client is None:
        return
    _redis_client.decr(_key(user_id))
