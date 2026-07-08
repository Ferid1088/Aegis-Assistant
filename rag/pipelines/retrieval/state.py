"""Retrieval pipeline state, singletons, and checkpointer."""

from typing import NotRequired, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from sentence_transformers import CrossEncoder

from rag.capabilities.search.search_service import SearchService
from rag.config import settings
from rag.crosscutting.context import Context
from rag.infra.models.llm import get_device
from rag.domain.models import RetrievedChunk
from rag.infra.stores.vector_store import get_shared_vector_store


class QueryState(TypedDict):
    question: str
    raw_question: NotRequired[str]
    standalone_question: NotRequired[str]
    doc_filter: NotRequired[dict]
    rewritten_query: NotRequired[str]
    expanded_query: NotRequired[str]
    dense_results: NotRequired[list[RetrievedChunk]]
    sparse_results: NotRequired[list[RetrievedChunk]]
    graph_results: NotRequired[list[RetrievedChunk]]
    fused: NotRequired[list[RetrievedChunk]]
    reranked: NotRequired[list[RetrievedChunk]]
    context: NotRequired[str]
    answer: NotRequired[str]
    citations: NotRequired[list[dict]]
    tenant_id: NotRequired[str]
    user_levels: NotRequired[list[str]]
    intended_types: NotRequired[list[str]]
    is_multi_hop: NotRequired[bool]
    plan: NotRequired[list[dict]]
    step_results: NotRequired[list[dict]]
    lang: NotRequired[str]
    answerability_verdict: NotRequired[str]
    assumptions: NotRequired[list[str]]
    clarification_question: NotRequired[str]
    unanswerable_reason: NotRequired[str]
    gate_candidate_rules: NotRequired[list[dict]]
    turn_history: NotRequired[list[dict]]
    repeat_cache: NotRequired[dict]
    normalized_question: NotRequired[str]
    cache_hit: NotRequired[bool]
    cached_answer: NotRequired[str]
    cached_citations: NotRequired[list[dict]]
    cached_context: NotRequired[str]
    was_contextualized: NotRequired[bool]
    is_followup: NotRequired[bool]
    conversation_id: NotRequired[str]
    conversation_state: NotRequired[str]
    lifecycle_blocked: NotRequired[bool]
    response_source: NotRequired[str]


# ── Singletons ───────────────────────────────────────────────────────────

_search: SearchService | None = None
_reranker: CrossEncoder | None = None
_MAX_TURNS = 8
_MAX_CACHE_ENTRIES = 20


def _make_checkpointer():
    if settings.checkpoint_db_path:
        try:
            import sqlite3
            from langgraph.checkpoint.sqlite import SqliteSaver
            conn = sqlite3.connect(settings.checkpoint_db_path, check_same_thread=False)
            saver = SqliteSaver(conn)
            saver.setup()
            return saver
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "SQLite checkpointer failed (%s) — falling back to InMemorySaver", exc
            )
    return InMemorySaver()


_checkpointer = _make_checkpointer()


def _get_search() -> SearchService:
    global _search
    if _search is None:
        # Explicitly pass the process-wide shared QdrantVectorStore (rather than
        # letting SearchService lazily create its own private one) so this
        # query-side singleton and rag/pipelines/ingestion/nodes.py's write-side singleton
        # never independently open a second handle on the same embedded Qdrant
        # storage -- see get_shared_vector_store()'s docstring for the
        # RuntimeError("...already accessed by another instance...") that used
        # to cause whenever a single process (e.g.
        # tests/integration/test_upload_and_chat_flow.py, via Celery's eager
        # mode) did both ingestion and querying.
        _search = SearchService(vec_store=get_shared_vector_store())
    return _search


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        dev = get_device()
        kwargs = {}
        if settings.reranker_use_fp16:
            import torch
            kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
        _reranker = CrossEncoder(settings.reranker_model, device=dev, **kwargs)
    return _reranker


def _make_ctx(state: QueryState) -> Context:
    return Context(
        tenant_id=state.get("tenant_id", "default"),
        user_levels=state.get("user_levels"),
    )
