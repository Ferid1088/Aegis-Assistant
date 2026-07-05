"""Exposes the Celery broker's pending-task queue length as a Prometheus gauge.

Uses Gauge.set_function(), not a manual polling thread: the gauge's value is
recomputed fresh every time Prometheus scrapes it (a real Redis LLEN call at scrape
time), matching Prometheus's own pull model rather than pushing stale cached values.
prometheus_client's start_http_server() already runs its own background thread
internally -- no additional threading code needed here.
"""

import redis
from prometheus_client import Gauge, start_http_server

from rag.config import settings

QUEUE_DEPTH = Gauge("celery_queue_depth", "Number of pending tasks in the Celery broker queue")

_QUEUE_NAME = "celery"  # Celery's default queue name when none is explicitly configured

# Lazily initialized on first call to _update_queue_depth
_redis_client = None


def _get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.redis_url)
    return _redis_client


def _update_queue_depth() -> None:
    if not settings.redis_url:
        return
    client = _get_redis_client()
    QUEUE_DEPTH.set_function(lambda: client.llen(_QUEUE_NAME))


def start_queue_depth_exporter(port: int = 9540) -> None:
    _update_queue_depth()
    start_http_server(port)
