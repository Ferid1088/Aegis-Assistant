import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, get_current_user, require_permission
from rag.api.schemas.documents import (
    JobResponse, JobStatusResponse, LogicalDocumentDetailResponse, LogicalDocumentResponse, VersionResponse,
)
from rag.config import settings
from rag.domain import ingestion_job_service
from rag.storage.document_store import SQLiteDocumentStore
from rag.storage.sql.base import get_db
from rag.worker.tasks import run_ingestion

router = APIRouter()


def _job_to_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=str(job.id), status=job.status, error=job.error,
        logical_doc_id=job.logical_doc_id, indexed_count=job.indexed_count,
    )


@router.post("", response_model=JobResponse, status_code=202)
def upload_document(
    file: UploadFile,
    current: AuthenticatedUser = Depends(require_permission("documents:upload")),
    db: Session = Depends(get_db),
) -> JobResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="only application/pdf is supported")

    contents = file.file.read()
    if len(contents) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file exceeds max upload size")

    job_id = uuid.uuid4()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    staged_path = upload_dir / f"{job_id}.pdf"
    staged_path.write_bytes(contents)

    job = ingestion_job_service.create_job(
        db, uploaded_by=current.user.id, filename=file.filename or "upload.pdf",
        staged_path=str(staged_path), doc_version=None,
    )
    run_ingestion.delay(str(job.id))
    return JobResponse(job_id=str(job.id))


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: uuid.UUID,
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    try:
        job = ingestion_job_service.get_job(db, job_id)
    except ingestion_job_service.JobNotFound as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc

    is_owner = job.uploaded_by == current.user.id
    is_admin = "admin:documents" in current.auth_subject.permissions
    if not (is_owner or is_admin):
        raise HTTPException(status_code=403, detail="not authorized to view this job")

    return _job_to_response(job)


@router.get("", response_model=list[LogicalDocumentResponse])
def list_documents(
    current: AuthenticatedUser = Depends(get_current_user),
) -> list[LogicalDocumentResponse]:
    store = SQLiteDocumentStore()
    return [
        LogicalDocumentResponse(
            logical_doc_id=d.logical_doc_id, source_identity=d.source_identity,
            document_type=d.document_type, state=d.state.value,
        )
        for d in store.list_logical_documents()
    ]


@router.get("/{logical_doc_id}", response_model=LogicalDocumentDetailResponse)
def get_document(
    logical_doc_id: str,
    current: AuthenticatedUser = Depends(get_current_user),
) -> LogicalDocumentDetailResponse:
    store = SQLiteDocumentStore()
    doc = store.get_logical_document(logical_doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    versions = store.get_versions(logical_doc_id)
    return LogicalDocumentDetailResponse(
        logical_doc_id=doc.logical_doc_id, source_identity=doc.source_identity,
        document_type=doc.document_type, state=doc.state.value,
        versions=[
            VersionResponse(
                version_id=v.version_id, version_no=v.version_no, filename=v.filename,
                num_pages=v.num_pages, is_active=v.is_active, processing_state=v.processing_state.value,
            )
            for v in versions
        ],
    )
