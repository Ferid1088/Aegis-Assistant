import sentry_sdk
import structlog
from celery import Celery
from celery.signals import task_postrun, task_prerun

from rag.config import settings
from rag.observability.logging_config import configure_logging
from rag.observability.queue_metrics import start_queue_depth_exporter

configure_logging()

if settings.glitchtip_dsn:
    sentry_sdk.init(dsn=settings.glitchtip_dsn, traces_sample_rate=0.0)

celery_app = Celery("rag_worker", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.autodiscover_tasks(["rag.worker"])


def _maybe_start_queue_depth_exporter() -> None:
    if settings.redis_url:
        start_queue_depth_exporter()


_maybe_start_queue_depth_exporter()


@task_prerun.connect
def _bind_task_id(task_id=None, **kwargs):
    structlog.contextvars.bind_contextvars(task_id=task_id)


@task_postrun.connect
def _clear_task_id(**kwargs):
    structlog.contextvars.clear_contextvars()
