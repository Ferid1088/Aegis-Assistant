"""Exposes the Celery broker's pending-task queue length as a Prometheus gauge.

Uses Gauge.set_function(), not a manual polling thread: the gauge's value is
recomputed fresh every time Prometheus scrapes it (a real Redis LLEN call at scrape
time), matching Prometheus's own pull model rather than pushing stale cached values.
prometheus_client's start_http_server() already runs its own background thread
internally -- no additional threading code needed here.
"""

import errno
import logging

import redis
from prometheus_client import Gauge, start_http_server

from rag.config import settings

logger = logging.getLogger(__name__)

QUEUE_DEPTH = Gauge("celery_queue_depth", "Number of pending tasks in the Celery broker queue")

_QUEUE_NAME = "celery"  # Celery's default queue name when none is explicitly configured


def _update_queue_depth() -> None:
    client = redis.Redis.from_url(settings.redis_url)
    QUEUE_DEPTH.set_function(lambda: client.llen(_QUEUE_NAME))


def start_queue_depth_exporter(port: int = 9540) -> None:
    _update_queue_depth()
    try:
        start_http_server(port)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        logger.debug("Queue-depth exporter port %d already bound, skipping", port)
