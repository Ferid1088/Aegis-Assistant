import uuid

import sentry_sdk
import structlog
from celery import Celery
from celery.signals import task_postrun, task_prerun, worker_init

from rag.config import settings
from rag.crosscutting.security.ingestion_limits import decrement_queued_ingestion
from rag.domain.ingestion_job_service import JobNotFound, get_job
from rag.observability.logging_config import configure_logging
from rag.observability.queue_metrics import start_queue_depth_exporter
from rag.storage.sql.base import SessionLocal

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


@worker_init.connect
def _start_queue_depth_exporter(**kwargs):
    _maybe_start_queue_depth_exporter()


@task_prerun.connect
def _bind_task_id(task_id=None, **kwargs):
    structlog.contextvars.bind_contextvars(task_id=task_id)


@task_postrun.connect
def _clear_task_id(**kwargs):
    structlog.contextvars.clear_contextvars()


@task_postrun.connect
def _decrement_ingestion_queue_count(sender=None, args=None, state=None, **kwargs):
    if sender is None or sender.name != "rag.worker.tasks.run_ingestion":
        return
    # task_postrun fires after every attempt, including ones that end via a
    # Retry exception (state="RETRY") -- there's only ever one INCR per job
    # (at upload time), so decrementing on retry attempts would drift the
    # counter negative. Only decrement once the job has truly finished.
    if state not in ("SUCCESS", "FAILURE"):
        return
    job_id = args[0] if args else None
    if job_id is None:
        return
    db = SessionLocal()
    try:
        try:
            job = get_job(db, uuid.UUID(job_id))
        except JobNotFound:
            return
        decrement_queued_ingestion(str(job.uploaded_by))
    finally:
        db.close()
