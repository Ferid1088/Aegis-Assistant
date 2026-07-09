"""Caps how many chat/generation requests can be simultaneously IN FLIGHT
against the shared LLM backend -- distinct from ingestion_limits.py's
per-user queued-ingestion cap. This is a single GLOBAL counter: the
constraint here is the shared vLLM/Ollama backend's total concurrent-
generation ceiling (the source doc's "~10-25 concurrent generations" for
one GPU), not any individual user's fair share.
"""

import redis

from rag.config import settings

_redis_client = redis.Redis.from_url(settings.redis_url) if settings.redis_url else None

_COUNTER_KEY = "generation_inflight"

# Backstop TTL for the counter -- self-heals if a decrement path is ever
# missed, matching ingestion_limits.py's identical convention. A chat
# request should never legitimately stay "in flight" anywhere near this
# long even at the per-request timeout's (Phase 8.10c) maximum.
_COUNTER_TTL_SECONDS = 10 * 60


def check_and_increment_inflight_generation(max_inflight: int) -> bool:
    if _redis_client is None:
        return True
    count = _redis_client.incr(_COUNTER_KEY)
    _redis_client.expire(_COUNTER_KEY, _COUNTER_TTL_SECONDS)
    if count > max_inflight:
        _redis_client.decr(_COUNTER_KEY)
        return False
    return True


def decrement_inflight_generation() -> None:
    if _redis_client is None:
        return
    _redis_client.decr(_COUNTER_KEY)
