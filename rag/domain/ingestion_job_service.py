import json
import uuid

from sqlalchemy.orm import Session

from rag.infra.stores.sql.models import IngestionJob


class JobNotFound(Exception):
    pass


def create_job(
    db: Session, *, uploaded_by: uuid.UUID, filename: str, staged_path: str, doc_version: str | None,
    target_logical_doc_id: str | None = None,
    department: str | None = None, document_type: str | None = None, access_level: list[str] | None = None,
) -> IngestionJob:
    job = IngestionJob(
        uploaded_by=uploaded_by,
        filename=filename,
        staged_path=staged_path,
        doc_version=doc_version,
        target_logical_doc_id=target_logical_doc_id,
        department=department,
        document_type=document_type,
        access_level=json.dumps(access_level) if access_level else None,
    )
    db.add(job)
    db.commit()
    return job


def get_job(db: Session, job_id: uuid.UUID) -> IngestionJob:
    job = db.get(IngestionJob, job_id)
    if job is None:
        raise JobNotFound()
    return job


def mark_running(db: Session, job: IngestionJob) -> IngestionJob:
    job.status = "running"
    db.commit()
    return job


def mark_done(
    db: Session, job: IngestionJob, *, logical_doc_id: str | None, indexed_count: int | None,
) -> IngestionJob:
    job.status = "done"
    job.logical_doc_id = logical_doc_id
    job.indexed_count = indexed_count
    db.commit()
    return job


def mark_failed(db: Session, job: IngestionJob, *, error: str) -> IngestionJob:
    job.status = "failed"
    job.error = error
    job.retry_count += 1
    db.commit()
    return job


def record_retry_attempt(db: Session, job: IngestionJob, *, error: str) -> IngestionJob:
    job.error = error
    job.retry_count += 1
    db.commit()
    return job


def list_jobs(db: Session, limit: int = 100) -> list[IngestionJob]:
    return (
        db.query(IngestionJob)
        .order_by(IngestionJob.created_at.desc())
        .limit(limit)
        .all()
    )
