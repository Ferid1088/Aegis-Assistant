import uuid

from rag.domain import ingestion_job_service
from rag.graphs.ingestion import build_ingestion_graph
from rag.storage.sql.base import SessionLocal
from rag.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, retry_backoff=True)
def run_ingestion(self, job_id: str) -> None:
    db = SessionLocal()
    try:
        job = ingestion_job_service.get_job(db, uuid.UUID(job_id))
        ingestion_job_service.mark_running(db, job)

        state = {"file_path": job.staged_path}
        if job.doc_version:
            state["doc_version"] = job.doc_version

        try:
            result = build_ingestion_graph().invoke(state)
        except Exception as exc:
            ingestion_job_service.mark_failed(db, job, error=str(exc))
            raise self.retry(exc=exc)

        status = result.get("status")
        if status == "error":
            ingestion_job_service.mark_failed(db, job, error=result.get("error", "unknown error"))
            return

        doc_meta = result.get("doc_meta")
        logical_doc_id = doc_meta.logical_doc_id if doc_meta is not None else None
        ingestion_job_service.mark_done(
            db, job, logical_doc_id=logical_doc_id, indexed_count=result.get("indexed_count"),
        )
    finally:
        db.close()
