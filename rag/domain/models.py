from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class BBox(BaseModel):
    page: int
    x: float
    y: float
    width: float
    height: float


class ChunkRecord(BaseModel):
    chunk_id: str
    type: str  # "text" | "table" | "table_row" | "table_full"
    content: str
    source_file: str
    doc_id: str
    doc_version: str | None = None
    page_numbers: list[int]
    heading_path: list[str]
    bboxes: list[BBox]
    keywords: list[str] = []
    summary: str | None = None
    value_num: float | None = None
    tenant_id: str = "default"
    acl_levels: list[str] = []
    document_type: str | None = None
    logical_doc_id: str | None = None  # reserved seam (02.1) — stable identity across versions
    is_current: bool = True


class DocumentMeta(BaseModel):
    doc_id: str
    filename: str
    content_hash: str
    num_pages: int
    doc_version: str | None = None
    is_current: bool = True
    superseded_by: str | None = None
    tenant_id: str = "default"
    source_document_ids: list[str] = []
    logical_doc_id: str | None = None  # reserved seam (02.1) — links this version to its LogicalDocument


class RetrievedChunk(BaseModel):
    chunk_id: str
    content: str
    score: float
    metadata: dict


class Predicate(BaseModel):
    variable: str
    operator: Literal[">=", "<=", "==", "!=", ">", "<", "in_range", "exists", "matches"]
    value: str | None = None
    value_high: str | None = None
    unit: str | None = None


class ComputationStep(BaseModel):
    from_state: str
    to_state: str
    increment: Decimal
    unit: str = "years"
    source_quote: str = ""
    page: int = 0


class Computation(BaseModel):
    type: Literal[
        "cumulative_steps",
        "threshold_lookup",
        "date_offset",
        "difference",
        "percentage_of",
        "proration",
        "operator_tree",
    ]
    steps: list[ComputationStep] = []
    thresholds: list[dict] = []
    tree: dict[str, Any] = Field(default_factory=dict)
    scope: dict = Field(default_factory=dict)


class RuleArtifact(BaseModel):
    type: Literal["rule"] = "rule"
    rule_id: str | None = None
    rule_kind: Literal["threshold", "mapping", "formula", "eligibility",
                        "deadline", "prohibition", "default", "progression"]
    trigger: str | None = None
    quality: Literal["valid", "uncertain", "invalid"] = "uncertain"
    statement: str
    conditions: list[Predicate] = []
    condition_logic: Literal["all", "any"] = "all"
    required_inputs: list[str] = []
    consequence: str
    variables: list[str] = []
    scope: list[Predicate] = []
    overrides: list[str] = []
    depends_on: list[str] = []
    domain: str
    source_doc_id: str
    source_page: int
    source_chunk_id: str
    source_quote: str = Field(max_length=200)
    doc_version: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    confidence: float
    computation: Computation | None = None
