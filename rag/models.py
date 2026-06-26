from pydantic import BaseModel


class BBox(BaseModel):
    page: int
    x: float
    y: float
    width: float
    height: float


class ChunkRecord(BaseModel):
    chunk_id: str
    type: str
    content: str
    source_file: str
    doc_id: str
    doc_version: str | None = None
    page_numbers: list[int]
    heading_path: list[str]
    bboxes: list[BBox]
    keywords: list[str] = []
    summary: str | None = None


class DocumentMeta(BaseModel):
    doc_id: str
    filename: str
    content_hash: str
    num_pages: int
    doc_version: str | None = None
    is_current: bool = True
    superseded_by: str | None = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    content: str
    score: float
    metadata: dict
