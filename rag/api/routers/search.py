from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from rag.api.deps import AuthenticatedUser, get_current_user
from rag.api.schemas.documents import (
    FacetResponse,
    FacetValueResponse,
    LogicalDocumentResponse,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
)
from rag.capabilities.search.search_service import SearchService
from rag.config import settings
from rag.crosscutting.security.acl import acl_filter, live_recheck
from rag.graphs.query import _rerank_impl  # reuse the same cross-encoder path as chat
from rag.storage.document_store import SQLiteDocumentStore
from rag.storage.vector_store import get_shared_vector_store

router = APIRouter()


def _doc_allowed(doc, current: AuthenticatedUser) -> bool:
    if not settings.acl_enforce:
        return True
    levels = set(current.auth_subject.effective_levels)
    doc_levels = set(doc.access_level or [])
    return bool(levels and doc_levels and levels & doc_levels)


def _summarize_document(store: SQLiteDocumentStore, doc) -> LogicalDocumentResponse:
    versions = store.get_versions(doc.logical_doc_id)
    active = next((v for v in versions if v.is_active), versions[-1] if versions else None)
    upload_date = active.created_at if active else doc.created_at
    last_modified = versions[-1].created_at if versions else None
    filename = active.filename if active else Path(doc.source_identity).name
    return LogicalDocumentResponse(
        id=doc.logical_doc_id,
        title=Path(filename).stem,
        department=doc.department,
        access_level=", ".join(doc.access_level) if doc.access_level else None,
        document_type=doc.document_type,
        project=store.get_project_name(doc.project_id),
        phase=store.get_phase_name(doc.phase_id),
        upload_date=upload_date.isoformat(),
        last_modified=last_modified.isoformat() if last_modified else None,
        active_version_no=active.version_no if active else 0,
        version_count=len(versions),
        file_type=Path(filename).suffix.lstrip(".").lower() or "pdf",
        state=doc.state.value,
    )


def _apply_doc_filters(summary: LogicalDocumentResponse, filters: dict[str, list[str]] | None) -> bool:
    if not filters:
        return True
    for key, values in filters.items():
        if not values:
            continue
        value = getattr(summary, key, None)
        if value is None:
            return False
        if value not in values:
            return False
    return True


@router.post("", response_model=SearchResponse)
def search_documents(
    body: SearchRequest,
    current: AuthenticatedUser = Depends(get_current_user),
) -> SearchResponse:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")

    store = SQLiteDocumentStore()
    search = SearchService(vec_store=get_shared_vector_store())
    flt = acl_filter(current.auth_subject.effective_levels) if settings.acl_enforce else None
    dense = search.search_dense(query, flt=flt)
    sparse = search.search_sparse(query, flt=flt)
    fused = SearchService.rrf([dense, sparse], k=settings.rrf_k)
    candidates = fused[: settings.fusion_candidates]
    reranked = _rerank_impl(query, candidates) if body.mode == "deep" else candidates
    allowed, _denied = live_recheck(reranked, current.auth_subject.effective_levels if settings.acl_enforce else None)

    grouped: dict[str, tuple[LogicalDocumentResponse, float, str, dict | None]] = {}
    visible_docs: dict[str, LogicalDocumentResponse] = {}
    for chunk in allowed:
        logical_doc_id = chunk.metadata.get("logical_doc_id")
        if not logical_doc_id:
            continue
        doc = store.get_logical_document(logical_doc_id)
        if doc is None or not _doc_allowed(doc, current):
            continue
        summary = _summarize_document(store, doc)
        visible_docs[logical_doc_id] = summary
        region = None
        bboxes = chunk.metadata.get("bboxes") or []
        if bboxes and isinstance(bboxes[0], dict):
            b = bboxes[0]
            if {"x", "y", "width", "height"} <= b.keys():
                region = [b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]]
        jump_to = None
        pages = chunk.metadata.get("page_numbers") or []
        if pages:
            jump_to = {"page": int(pages[0])}
            if region:
                jump_to["region"] = region
        existing = grouped.get(logical_doc_id)
        if existing is None or chunk.score > existing[1]:
            grouped[logical_doc_id] = (summary, float(chunk.score), chunk.content[:280], jump_to)

    doc_hits = []
    for summary, relevance, snippet, jump_to in grouped.values():
        if _apply_doc_filters(summary, body.filters):
            doc_hits.append(SearchHitResponse(document=summary, relevance=relevance, snippet=snippet, jump_to=jump_to))
    doc_hits.sort(key=lambda hit: hit.relevance, reverse=True)

    def _facet(field: str, label: str) -> FacetResponse:
        counts = Counter(getattr(doc, field) for doc in visible_docs.values() if getattr(doc, field))
        return FacetResponse(
            field=field,
            label=label,
            values=[FacetValueResponse(value=value, count=count) for value, count in counts.items()],
        )

    facets = [
        _facet("department", "Department"),
        _facet("document_type", "Document type"),
        _facet("project", "Project"),
    ]
    return SearchResponse(hits=doc_hits, facets=facets)