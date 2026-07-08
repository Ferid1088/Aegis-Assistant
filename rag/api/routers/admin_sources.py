from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, require_permission
from rag.domain import ingestion_job_service
from rag.infra.stores.document_store import SQLiteDocumentStore
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import DocumentSourceConfig

router = APIRouter()


class SourceCreateRequest(BaseModel):
    name: str
    kind: str
    location: str
    path_mapping: str | None = None


class SourceUpdateRequest(BaseModel):
    enabled: bool


class SourceResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    name: str
    kind: str
    enabled: bool
    location: str
    path_mapping: str | None
    last_scan: str | None
    status: str


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    document_title: str
    state: str
    progress: int
    source_name: str
    started_at: str
    error: str | None


class QuarantineItemResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    document_title: str
    reason: str
    stage: str
    quarantined_at: str


def _source_to_response(source: DocumentSourceConfig) -> SourceResponse:
    return SourceResponse(
        id=str(source.id),
        name=source.name,
        kind=source.kind,
        enabled=source.enabled,
        location=source.location,
        path_mapping=source.path_mapping,
        last_scan=source.last_scan.isoformat() if source.last_scan else None,
        status=source.status,
    )


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(
    current: AuthenticatedUser = Depends(require_permission("admin:sources")),
    db: Session = Depends(get_db),
) -> list[SourceResponse]:
    sources = db.execute(select(DocumentSourceConfig).order_by(DocumentSourceConfig.name.asc())).scalars().all()
    return [_source_to_response(source) for source in sources]


@router.post("/sources", response_model=SourceResponse, status_code=201)
def create_source(
    body: SourceCreateRequest,
    current: AuthenticatedUser = Depends(require_permission("admin:sources")),
    db: Session = Depends(get_db),
) -> SourceResponse:
    source = DocumentSourceConfig(
        name=body.name,
        kind=body.kind,
        location=body.location,
        path_mapping=body.path_mapping,
        enabled=True,
        status="connected",
        last_scan=datetime.now(timezone.utc),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_to_response(source)


@router.patch("/sources/{source_id}", response_model=SourceResponse)
def update_source(
    source_id: str,
    body: SourceUpdateRequest,
    current: AuthenticatedUser = Depends(require_permission("admin:sources")),
    db: Session = Depends(get_db),
) -> SourceResponse:
    source = db.get(DocumentSourceConfig, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    source.enabled = body.enabled
    source.status = "connected" if body.enabled else "disabled"
    source.last_scan = datetime.now(timezone.utc)
    db.commit()
    db.refresh(source)
    return _source_to_response(source)


@router.get("/ingestion/jobs", response_model=list[IngestionJobResponse])
def list_ingestion_jobs(
    current: AuthenticatedUser = Depends(require_permission("admin:documents")),
    db: Session = Depends(get_db),
) -> list[IngestionJobResponse]:
    jobs = ingestion_job_service.list_jobs(db)
    return [
        IngestionJobResponse(
            id=str(job.id),
            document_title=job.filename,
            state=job.status,
            progress=100 if job.status == "done" else 0,
            source_name="manual upload",
            started_at=job.created_at.isoformat(),
            error=job.error,
        )
        for job in jobs
    ]


@router.get("/quarantine", response_model=list[QuarantineItemResponse])
def list_quarantine(
    current: AuthenticatedUser = Depends(require_permission("admin:documents")),
) -> list[QuarantineItemResponse]:
    store = SQLiteDocumentStore()
    items: list[QuarantineItemResponse] = []
    for doc in store.list_logical_documents():
        for version in store.get_versions(doc.logical_doc_id):
            if version.processing_state.value != "quarantined":
                continue
            items.append(
                QuarantineItemResponse(
                    id=version.version_id,
                    document_title=version.filename,
                    reason="Requires manual review",
                    stage=version.processing_state.value,
                    quarantined_at=version.updated_at.isoformat(),
                )
            )
    return items