from pydantic import BaseModel


class JobResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: str | None
    logical_doc_id: str | None
    indexed_count: int | None


class VersionResponse(BaseModel):
    version_id: str
    version_no: int
    filename: str
    num_pages: int
    is_active: bool
    processing_state: str


class LogicalDocumentResponse(BaseModel):
    logical_doc_id: str
    source_identity: str
    document_type: str | None
    state: str


class LogicalDocumentDetailResponse(LogicalDocumentResponse):
    versions: list[VersionResponse]
