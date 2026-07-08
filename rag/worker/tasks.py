import json
import uuid
from pathlib import Path

from rag.domain import ingestion_job_service
from rag.graphs.ingestion import build_ingestion_graph
from rag.infra.stores.sql.base import SessionLocal
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
        if job.target_logical_doc_id:
            state["target_logical_doc_id"] = job.target_logical_doc_id
        if job.department:
            state["department"] = job.department
        if job.document_type:
            state["document_type"] = job.document_type
        if job.access_level:
            state["access_level"] = json.loads(job.access_level)

        try:
            result = build_ingestion_graph().invoke(state)
        except Exception as exc:
            if self.request.retries < self.max_retries:
                ingestion_job_service.record_retry_attempt(db, job, error=str(exc))
                raise self.retry(exc=exc)
            ingestion_job_service.mark_failed(db, job, error=str(exc))
            Path(job.staged_path).unlink(missing_ok=True)
            return

        status = result.get("status")
        if status == "error":
            ingestion_job_service.mark_failed(db, job, error=result.get("error", "unknown error"))
            Path(job.staged_path).unlink(missing_ok=True)
            return

        doc_meta = result.get("doc_meta")
        logical_doc_id = doc_meta.logical_doc_id if doc_meta is not None else None
        ingestion_job_service.mark_done(
            db, job, logical_doc_id=logical_doc_id, indexed_count=result.get("indexed_count"),
        )
        Path(job.staged_path).unlink(missing_ok=True)
    finally:
        db.close()
