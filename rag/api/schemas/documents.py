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
    num_pages: int | None
    is_active: bool
    processing_state: str
    uploaded_at: str
    file_type: str


class LogicalDocumentResponse(BaseModel):
    id: str
    title: str
    department: str | None
    access_level: str | None
    document_type: str | None
    project: str | None
    phase: str | None
    upload_date: str
    last_modified: str | None
    active_version_no: int
    version_count: int
    file_type: str
    state: str


class LogicalDocumentDetailResponse(LogicalDocumentResponse):
    versions: list[VersionResponse]
    can_manage: bool


class ActivateVersionRequest(BaseModel):
    version_id: str | None = None
    version_no: int | None = None


class DocumentMetadataUpdate(BaseModel):
    department: str | None = None
    document_type: str | None = None
    access_level: list[str] | None = None


class SearchRequest(BaseModel):
    query: str
    mode: str = "deep"
    filters: dict[str, list[str]] | None = None


class SearchHitResponse(BaseModel):
    document: LogicalDocumentResponse
    snippet: str
    relevance: float
    jump_to: dict[str, int | list[float]] | None = None


class FacetValueResponse(BaseModel):
    value: str
    count: int


class FacetResponse(BaseModel):
    field: str
    label: str
    values: list[FacetValueResponse]


class SearchResponse(BaseModel):
    hits: list[SearchHitResponse]
    facets: list[FacetResponse]
