"""Query pipeline: question → transform → dense+sparse retrieval → RRF → rerank → generate."""

import json
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from sentence_transformers import CrossEncoder

from rag.config import settings
from rag.llm.provider import get_device, get_embedder, get_llm, get_sparse_embedder
from rag.models import RetrievedChunk
from rag.storage.vector_store import QdrantVectorStore


class QueryState(TypedDict):
    question: str
    doc_filter: NotRequired[dict]
    rewritten_query: NotRequired[str]
    expanded_query: NotRequired[str]
    dense_results: NotRequired[list[RetrievedChunk]]
    sparse_results: NotRequired[list[RetrievedChunk]]
    fused: NotRequired[list[RetrievedChunk]]
    reranked: NotRequired[list[RetrievedChunk]]
    context: NotRequired[str]
    answer: NotRequired[str]
    citations: NotRequired[list[dict]]


# ── Helpers ──────────────────────────────────────────────────────────────

def rrf(result_lists: list[list[RetrievedChunk]], k: int = 60) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    by_id: dict[str, RetrievedChunk] = {}
    for lst in result_lists:
        for rank, ch in enumerate(lst):
            scores[ch.chunk_id] = scores.get(ch.chunk_id, 0) + 1.0 / (k + rank)
            by_id[ch.chunk_id] = ch
    ranked = sorted(scores, key=scores.get, reverse=True)
    return [by_id[cid] for cid in ranked]


_store = None
_reranker = None


def _get_store() -> QdrantVectorStore:
    global _store
    if _store is None:
        _store = QdrantVectorStore()
    return _store


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        dev = get_device()
        _reranker = CrossEncoder(
            settings.reranker_model,
            device=dev,
        )
    return _reranker


TRANSFORM_PROMPT = """\
You are a search query optimizer for German legal/HR documents (TV-L, collective agreements).
Given a user question, produce a JSON object with two fields:
- "rewritten": the question rewritten with precise German technical/legal terms (for dense vector search)
- "expanded": the question expanded with German synonyms and related terms (for sparse keyword search)

Rules:
- Output ONLY valid JSON, no explanation.
- Keep both fields in German.

Question: {question}
"""

GENERATION_PROMPT = """\
Du bist ein Assistent für den Tarifvertrag der Länder (TV-L).
Beantworte die Frage NUR anhand des folgenden Kontexts.
Verwende [n]-Markierungen, um auf Quellen zu verweisen.
Wenn die Antwort nicht im Kontext enthalten ist, sage explizit: "Die Antwort wurde im Dokument nicht gefunden."

Kontext:
{context}

Frage: {question}

Antwort:"""


# ── Nodes ────────────────────────────────────────────────────────────────

def transform_query(state: QueryState) -> dict:
    llm = get_llm()
    prompt = TRANSFORM_PROMPT.format(question=state["question"])
    response = llm.invoke(prompt)

    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
        rewritten = parsed.get("rewritten", state["question"])
        expanded = parsed.get("expanded", state["question"])
    except (json.JSONDecodeError, AttributeError, IndexError):
        rewritten = state["question"]
        expanded = state["question"]

    print(f"🔄 Rewritten: {rewritten}")
    print(f"🔄 Expanded:  {expanded}")
    return {"rewritten_query": rewritten, "expanded_query": expanded}


def retrieve_dense(state: QueryState) -> dict:
    embedder = get_embedder()
    store = _get_store()
    queries = [state["question"], state.get("rewritten_query", state["question"])]
    vecs = [v.tolist() for v in embedder.embed(queries)]
    hits = [
        store.search_dense(v, settings.dense_top_k, state.get("doc_filter"))
        for v in vecs
    ]
    fused = rrf(hits, k=settings.rrf_k)
    print(f"🔍 Dense: {len(fused)} unique chunks from {sum(len(h) for h in hits)} hits")
    return {"dense_results": fused}


def retrieve_sparse(state: QueryState) -> dict:
    sparse_embedder = get_sparse_embedder()
    store = _get_store()
    queries = [state["question"], state.get("expanded_query", state["question"])]
    svecs = list(sparse_embedder.embed(queries))
    hits = [
        store.search_sparse(
            {"indices": sv.indices.tolist(), "values": sv.values.tolist()},
            settings.sparse_top_k,
            state.get("doc_filter"),
        )
        for sv in svecs
    ]
    fused = rrf(hits, k=settings.rrf_k)
    print(f"🔍 Sparse: {len(fused)} unique chunks from {sum(len(h) for h in hits)} hits")
    return {"sparse_results": fused}


def rrf_fuse(state: QueryState) -> dict:
    lists = [state["dense_results"], state["sparse_results"]]
    fused = rrf(lists, k=settings.rrf_k)
    candidates = fused[: settings.fusion_candidates]
    print(f"🔀 RRF fused: {len(fused)} total → top {len(candidates)} to reranker")
    return {"fused": candidates}


def rerank(state: QueryState) -> dict:
    q = state["question"]
    cands = state["fused"]
    pairs = [[q, c.content] for c in cands]
    scores = get_reranker().predict(pairs)

    print(f"⭐ Reranker fused top-3:  {[c.chunk_id[:8] for c in cands[:3]]}")

    reranked = []
    for c, s in zip(cands, scores):
        reranked.append(RetrievedChunk(
            chunk_id=c.chunk_id,
            content=c.content,
            score=float(s),
            metadata=c.metadata,
        ))
    reranked.sort(key=lambda c: c.score, reverse=True)
    top = reranked[: settings.rerank_top_k]

    print(f"⭐ Reranker reranked top-3: {[c.chunk_id[:8] for c in top[:3]]}")
    return {"reranked": top}


def generate(state: QueryState) -> dict:
    llm = get_llm()
    ctx = "\n\n".join(
        f"[{i + 1}] (p.{c.metadata['page_numbers']}) {c.content}"
        for i, c in enumerate(state["reranked"])
    )
    prompt = GENERATION_PROMPT.format(question=state["question"], context=ctx)
    answer = llm.invoke(prompt)

    citations = [
        {
            "chunk_id": c.chunk_id,
            "page_numbers": c.metadata["page_numbers"],
            "section": c.metadata.get("heading_path", []),
            "bboxes": c.metadata["bboxes"],
        }
        for c in state["reranked"]
    ]

    return {"answer": answer.content, "citations": citations, "context": ctx}


# ── Graph ────────────────────────────────────────────────────────────────

def build_query_graph():
    g = StateGraph(QueryState)
    g.add_node("transform_query", transform_query)
    g.add_node("retrieve_dense", retrieve_dense)
    g.add_node("retrieve_sparse", retrieve_sparse)
    g.add_node("rrf_fuse", rrf_fuse)
    g.add_node("rerank", rerank)
    g.add_node("generate", generate)

    g.add_edge(START, "transform_query")
    g.add_edge("transform_query", "retrieve_dense")
    g.add_edge("transform_query", "retrieve_sparse")
    g.add_edge("retrieve_dense", "rrf_fuse")
    g.add_edge("retrieve_sparse", "rrf_fuse")
    g.add_edge("rrf_fuse", "rerank")
    g.add_edge("rerank", "generate")
    g.add_edge("generate", END)

    return g.compile()
