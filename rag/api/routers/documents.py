import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, get_current_user, require_permission
from rag.api.schemas.documents import (
    ActivateVersionRequest,
    JobResponse,
    JobStatusResponse,
    LogicalDocumentDetailResponse,
    LogicalDocumentResponse,
    UpdateDocumentMetadataRequest,
    VersionResponse,
)
from rag.config import settings
from rag.crosscutting.security.ingestion_limits import (
    check_and_increment_queued_ingestion, decrement_queued_ingestion,
)
from rag.crosscutting.security.rate_limit import limiter
from rag.domain import ingestion_job_service
from rag.infra.stores.document_store import SQLiteDocumentStore
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import AccessLevel, Department, DocumentType
from rag.worker.tasks import run_ingestion

router = APIRouter()


def _job_to_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=str(job.id), status=job.status, error=job.error,
        logical_doc_id=job.logical_doc_id, indexed_count=job.indexed_count,
    )


def _doc_allowed(doc, current: AuthenticatedUser) -> bool:
    if not settings.acl_enforce:
        return True
    user_levels = set(current.auth_subject.effective_levels)
    doc_levels = set(doc.access_level or [])
    return bool(user_levels and doc_levels and user_levels & doc_levels)


def _version_response(version) -> VersionResponse:
    return VersionResponse(
        version_id=version.version_id,
        version_no=version.version_no,
        filename=version.filename,
        num_pages=version.num_pages,
        is_active=version.is_active,
        processing_state=version.processing_state.value,
        uploaded_at=version.created_at.isoformat(),
        file_type=Path(version.filename).suffix.lstrip(".").lower() or "pdf",
    )


def _document_response(db: Session, store: SQLiteDocumentStore, doc, *, can_manage: bool | None = None):
    versions = store.get_versions(doc.logical_doc_id)
    active = next((v for v in versions if v.is_active), versions[-1] if versions else None)
    filename = active.filename if active else Path(doc.source_identity).name
    payload = dict(
        id=doc.logical_doc_id,
        title=doc.title or Path(filename).stem,
        department=_resolve_department_name(db, doc.department),
        department_id=doc.department,
        access_level=_resolve_access_level_names(db, doc.access_level),
        access_level_ids=doc.access_level,
        document_type=_resolve_document_type_name(db, doc.document_type),
        document_type_id=doc.document_type,
        project=store.get_project_name(doc.project_id),
        phase=store.get_phase_name(doc.phase_id),
        upload_date=(active.created_at if active else doc.created_at).isoformat(),
        last_modified=versions[-1].updated_at.isoformat() if versions else None,
        active_version_no=active.version_no if active else 0,
        version_count=len(versions),
        file_type=Path(filename).suffix.lstrip(".").lower() or "pdf",
        state=doc.state.value,
    )
    if can_manage is None:
        return LogicalDocumentResponse(**payload)
    return LogicalDocumentDetailResponse(
        **payload,
        versions=[_version_response(v) for v in versions],
        can_manage=can_manage,
    )


def _get_document_or_404(store: SQLiteDocumentStore, logical_doc_id: str):
    doc = store.get_logical_document(logical_doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


def _parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="malformed id") from exc


def _validate_document_metadata(
    db: Session, department_id: str, document_type_id: str | None, access_level_ids: list[str],
) -> None:
    dept = db.get(Department, _parse_id(department_id))
    if dept is None:
        raise HTTPException(status_code=404, detail="department not found")
    if document_type_id is not None:
        dtype = db.get(DocumentType, _parse_id(document_type_id))
        if dtype is None:
            raise HTTPException(status_code=404, detail="document type not found")
    if not access_level_ids:
        raise HTTPException(status_code=400, detail="at least one access level is required")
    level_uuids = [_parse_id(level_id) for level_id in access_level_ids]
    matched = db.execute(
        select(AccessLevel).where(AccessLevel.id.in_(level_uuids), AccessLevel.department_id == dept.id)
    ).scalars().all()
    if len(matched) != len(level_uuids):
        raise HTTPException(status_code=400, detail="one or more access levels not found for this department")


def _resolve_department_name(db: Session, department_id: str | None) -> str | None:
    if not department_id:
        return None
    try:
        dept_uuid = uuid.UUID(department_id)
    except ValueError:
        return "Unknown department"
    dept = db.get(Department, dept_uuid)
    return dept.name if dept else "Unknown department"


def _resolve_document_type_name(db: Session, document_type_id: str | None) -> str | None:
    if not document_type_id:
        return None
    try:
        dtype_uuid = uuid.UUID(document_type_id)
    except ValueError:
        return "Unknown type"
    dtype = db.get(DocumentType, dtype_uuid)
    return dtype.label if dtype else "Unknown type"


def _resolve_access_level_names(db: Session, access_level_ids: list[str]) -> str | None:
    if not access_level_ids:
        return None
    ids = []
    valid_ids = set()
    for level_id in access_level_ids:
        try:
            ids.append(uuid.UUID(level_id))
            valid_ids.add(level_id)
        except ValueError:
            continue
    levels = db.execute(select(AccessLevel).where(AccessLevel.id.in_(ids))).scalars().all() if ids else []
    found = {str(lv.id): lv.label for lv in levels}
    return ", ".join(found.get(level_id, "Unknown access level") for level_id in access_level_ids)


@router.post("", response_model=JobResponse, status_code=202)
@limiter.limit("5/minute")
def upload_document(
    request: Request,
    file: UploadFile,
    logical_doc_id: str | None = Form(default=None),
    title: str | None = Form(default=None),
    department_id: str | None = Form(default=None),
    document_type_id: str | None = Form(default=None),
    access_level_ids: list[str] = Form(default=[]),
    current: AuthenticatedUser = Depends(require_permission("documents:upload")),
    db: Session = Depends(get_db),
) -> JobResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="only application/pdf is supported")

    contents = file.file.read()
    if len(contents) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file exceeds max upload size")

    if logical_doc_id is None:
        if not title or not department_id or not document_type_id or not access_level_ids:
            raise HTTPException(status_code=422, detail="title, department_id, document_type_id, and access_level_ids are required for a new document")
        _validate_document_metadata(db, department_id, document_type_id, access_level_ids)

    if not check_and_increment_queued_ingestion(str(current.user.id)):
        raise HTTPException(status_code=429, detail="too many queued ingestion jobs, wait for one to finish")

    job_id = uuid.uuid4()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    staged_path = upload_dir / f"{job_id}.pdf"

    try:
        staged_path.write_bytes(contents)

        if logical_doc_id is not None:
            store = SQLiteDocumentStore()
            target = _get_document_or_404(store, logical_doc_id)
            if not _doc_allowed(target, current):
                raise HTTPException(status_code=403, detail="not authorized to manage this document")
            if "documents:manage_versions" not in current.auth_subject.permissions:
                raise HTTPException(status_code=403, detail="missing permission: documents:manage_versions")

        job = ingestion_job_service.create_job(
            db, uploaded_by=current.user.id, filename=file.filename or "upload.pdf",
            staged_path=str(staged_path), doc_version=None,
            target_logical_doc_id=logical_doc_id,
            title=title if logical_doc_id is None else None,
            department_id=department_id if logical_doc_id is None else None,
            document_type_id=document_type_id if logical_doc_id is None else None,
            access_level_ids=access_level_ids if logical_doc_id is None else None,
        )
        run_ingestion.delay(str(job.id))
    except Exception:
        decrement_queued_ingestion(str(current.user.id))
        raise
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
    db: Session = Depends(get_db),
) -> list[LogicalDocumentResponse]:
    store = SQLiteDocumentStore()
    return [
        _document_response(db, store, d)
        for d in store.list_logical_documents()
        if _doc_allowed(d, current)
    ]


@router.get("/{logical_doc_id}", response_model=LogicalDocumentDetailResponse)
def get_document(
    logical_doc_id: str,
    current: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LogicalDocumentDetailResponse:
    store = SQLiteDocumentStore()
    doc = _get_document_or_404(store, logical_doc_id)
    if not _doc_allowed(doc, current):
        raise HTTPException(status_code=404, detail="document not found")

    return _document_response(
        db, store, doc,
        can_manage="documents:manage_versions" in current.auth_subject.permissions,
    )


@router.patch("/{logical_doc_id}/versions/{version_id}", response_model=LogicalDocumentDetailResponse)
def activate_document_version(
    logical_doc_id: str,
    version_id: str,
    body: ActivateVersionRequest,
    current: AuthenticatedUser = Depends(require_permission("documents:manage_versions")),
    db: Session = Depends(get_db),
) -> LogicalDocumentDetailResponse:
    store = SQLiteDocumentStore()
    doc = _get_document_or_404(store, logical_doc_id)
    if not _doc_allowed(doc, current):
        raise HTTPException(status_code=404, detail="document not found")

    target_version_id = body.version_id or version_id
    if body.version_no is not None:
        match = next((v for v in store.get_versions(logical_doc_id) if v.version_no == body.version_no), None)
        if match is None:
            raise HTTPException(status_code=404, detail="version not found")
        target_version_id = match.version_id
    store.activate_version(target_version_id)
    return _document_response(db, store, doc, can_manage=True)


@router.patch("/{logical_doc_id}/metadata", response_model=LogicalDocumentDetailResponse)
def update_document_metadata(
    logical_doc_id: str,
    body: UpdateDocumentMetadataRequest,
    current: AuthenticatedUser = Depends(require_permission("documents:manage_versions")),
    db: Session = Depends(get_db),
) -> LogicalDocumentDetailResponse:
    store = SQLiteDocumentStore()
    doc = _get_document_or_404(store, logical_doc_id)
    if not _doc_allowed(doc, current):
        raise HTTPException(status_code=404, detail="document not found")

    effective_department_id = body.department_id if body.department_id is not None else doc.department
    effective_document_type_id = body.document_type_id if body.document_type_id is not None else doc.document_type
    effective_access_level_ids = body.access_level_ids if body.access_level_ids is not None else doc.access_level
    if effective_department_id:
        _validate_document_metadata(db, effective_department_id, effective_document_type_id, effective_access_level_ids)

    store.update_logical_document_metadata(
        logical_doc_id, title=body.title, department=body.department_id,
        document_type=body.document_type_id, access_level=body.access_level_ids,
    )
    updated = _get_document_or_404(store, logical_doc_id)
    return _document_response(db, store, updated, can_manage=True)


@router.get("/{logical_doc_id}/render")
def render_document_page(
    logical_doc_id: str,
    v: int | None = None,
    page: int = 1,
    current: AuthenticatedUser = Depends(get_current_user),
):
    store = SQLiteDocumentStore()
    doc = _get_document_or_404(store, logical_doc_id)
    if not _doc_allowed(doc, current):
        raise HTTPException(status_code=404, detail="document not found")

    versions = store.get_versions(logical_doc_id)
    version = next((item for item in versions if item.version_no == v), None) if v is not None else None
    if version is None:
        version = next((item for item in versions if item.is_active), versions[-1] if versions else None)
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")

    image_path = Path(settings.document_pages_dir) / version.version_id / f"page_{page}.png"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="rendered page not found")
    return FileResponse(image_path, media_type="image/png")
