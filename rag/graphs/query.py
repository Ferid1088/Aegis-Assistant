"""Query pipeline: question → transform → dense+sparse+graph retrieval → RRF → rerank → generate.

Nodes are THIN: read state → call capability → write state.
Search goes through capabilities/search/SearchService. Extraction through capabilities/extract.
"""

import json
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from sentence_transformers import CrossEncoder

from rag.capabilities.search.search_service import SearchService
from rag.config import settings
from rag.crosscutting.context import Context
from rag.crosscutting.observability.tracing import traced
from rag.crosscutting.security.acl import acl_filter, live_recheck, log_retrieval_audit, type_filter
from rag.llm.provider import get_device, get_llm
from rag.models import RetrievedChunk


class QueryState(TypedDict):
    question: str
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


# ── Singletons ───────────────────────────────────────────────────────────

_search: SearchService | None = None
_reranker: CrossEncoder | None = None


def _get_search() -> SearchService:
    global _search
    if _search is None:
        _search = SearchService()
    return _search


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        dev = get_device()
        _reranker = CrossEncoder(settings.reranker_model, device=dev)
    return _reranker


def _make_ctx(state: QueryState) -> Context:
    return Context(
        tenant_id=state.get("tenant_id", "default"),
        user_levels=state.get("user_levels"),
    )


# ── Prompts ──────────────────────────────────────────────────────────────

TRANSFORM_PROMPT = """\
You are a search query optimizer for German legal/HR documents (TV-L, collective agreements).
Given a user question, produce a JSON object with four fields:
- "rewritten": the question rewritten with precise German technical/legal terms (for dense vector search)
- "expanded": the question expanded with German synonyms and related terms (for sparse keyword search)
- "entities": a list of key entity names mentioned or implied (for graph lookup)
- "lang": the ISO 639-1 code of the language the QUESTION SENTENCE is written in (e.g. "de", "en"). \
Judge by the sentence grammar and function words (what/was/wie/welche), NOT by domain terms like \
"Stufe" or "E12" which are always German regardless of question language.

Rules:
- Output ONLY valid JSON, no explanation.
- Keep rewritten and expanded in German (for retrieval).
- entities should be canonical German terms.
- "lang": detect from the QUESTION sentence structure, not domain vocabulary.

Question: {question}
"""

GENERATION_PROMPT = """\
You are an assistant for tariff/HR documents (TV-L).
Answer EXCLUSIVELY in this language (ISO code): {lang}.
Answer in {lang} even if the context is in another language. Translate facts from the \
context into {lang} as needed.
Use ONLY the provided context. Use [n] markers to cite sources.
If the answer is not in the context, say so in {lang} — do not invent.

Context:
{context}

Question: {question}

Reminder: respond ONLY in {lang}."""

SYNTHESIZE_PROMPT = """\
You are an assistant for tariff/HR documents (TV-L).
Answer EXCLUSIVELY in this language (ISO code): {lang}.
Synthesize the step results into a complete answer in {lang}.
Translate any facts from the context into {lang} as needed.
Use [n] markers for sources. If a step found no answer, say so in {lang}.

Original question: {question}

Steps and results:
{steps}

Context:
{context}

Reminder: respond ONLY in {lang}."""


_EN_MARKERS = {"what", "how", "which", "does", "is", "are", "can", "do", "will",
               "who", "where", "when", "why", "could", "should", "would", "tell"}
_DE_MARKERS = {"was", "wie", "welche", "welcher", "welches", "wer", "wo", "wann",
               "warum", "ist", "sind", "kann", "gibt", "werden", "hat", "soll"}


def _detect_lang_heuristic(question: str) -> str:
    words = question.lower().split()[:4]
    for w in words:
        if w in _EN_MARKERS:
            return "en"
        if w in _DE_MARKERS:
            return "de"
    return "de"


# ── Nodes (thin: read state → call capability → write state) ─────────────

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
        lang = parsed.get("lang", "de")
    except (json.JSONDecodeError, AttributeError, IndexError):
        rewritten = state["question"]
        expanded = state["question"]
        lang = "de"

    heuristic_lang = _detect_lang_heuristic(state["question"])
    if not isinstance(lang, str) or len(lang) != 2:
        lang = heuristic_lang
    elif heuristic_lang != lang and heuristic_lang == "en":
        lang = "en"

    print(f"🔄 Rewritten: {rewritten}")
    print(f"🔄 Expanded:  {expanded}")
    print(f"🌐 Language:  {lang}")
    return {"rewritten_query": rewritten, "expanded_query": expanded, "lang": lang}


def _build_retrieval_filter(state: QueryState) -> dict | None:
    flt = dict(state.get("doc_filter") or {})
    acl = acl_filter(state.get("user_levels"))
    if acl:
        flt.update(acl)
    tf = type_filter(state.get("intended_types"))
    if tf:
        flt.update(tf)
    if settings.acl_enforce and state.get("tenant_id"):
        flt["tenant_id"] = state["tenant_id"]
    return flt or None


def retrieve_dense(state: QueryState) -> dict:
    search = _get_search()
    ctx = _make_ctx(state)
    flt = _build_retrieval_filter(state)
    queries = [state["question"], state.get("rewritten_query", state["question"])]
    hits = search.search_dense_multi(queries, flt=flt, ctx=ctx)
    fused = SearchService.rrf(hits, k=settings.rrf_k, ctx=ctx)
    print(f"🔍 Dense: {len(fused)} unique chunks from {sum(len(h) for h in hits)} hits")
    return {"dense_results": fused}


def retrieve_sparse(state: QueryState) -> dict:
    search = _get_search()
    ctx = _make_ctx(state)
    flt = _build_retrieval_filter(state)
    queries = [state["question"], state.get("expanded_query", state["question"])]
    hits = search.search_sparse_multi(queries, flt=flt, ctx=ctx)
    fused = SearchService.rrf(hits, k=settings.rrf_k, ctx=ctx)
    print(f"🔍 Sparse: {len(fused)} unique chunks from {sum(len(h) for h in hits)} hits")
    return {"sparse_results": fused}


def retrieve_graph(state: QueryState) -> dict:
    search = _get_search()
    ctx = _make_ctx(state)

    llm = get_llm()
    prompt = (
        "Extract key entity names from this question for graph lookup. "
        "Return ONLY a JSON array of strings (canonical German terms). "
        f"Question: {state['question']}"
    )
    response = llm.invoke(prompt)
    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        entities = json.loads(text)
        if not isinstance(entities, list):
            entities = []
    except (json.JSONDecodeError, IndexError):
        entities = []

    if not entities:
        return {"graph_results": []}

    print(f"🔗 Graph query entities: {entities}")
    allowed = state.get("user_levels") if settings.acl_enforce else None
    results = search.search_graph(entities, hops=2, allowed_levels=allowed, ctx=ctx)
    print(f"🔗 Graph: {len(results)} chunks")
    return {"graph_results": results}


def rrf_fuse(state: QueryState) -> dict:
    ctx = _make_ctx(state)
    lists = [state.get("dense_results", []), state.get("sparse_results", [])]
    graph = state.get("graph_results", [])
    if graph:
        lists.append(graph)
    fused = SearchService.rrf(lists, k=settings.rrf_k, ctx=ctx)
    candidates = fused[: settings.fusion_candidates]
    n_sources = 2 + (1 if graph else 0)
    print(f"🔀 RRF fused ({n_sources} sources): {len(fused)} total → top {len(candidates)} to reranker")
    return {"fused": candidates}


@traced("rerank.cross_encoder")
def _rerank_impl(question: str, candidates: list[RetrievedChunk],
                 ctx: Context | None = None) -> list[RetrievedChunk]:
    if not candidates:
        return []
    pairs = [[question, c.content] for c in candidates]
    scores = _get_reranker().predict(pairs)
    reranked = [
        RetrievedChunk(chunk_id=c.chunk_id, content=c.content,
                       score=float(s), metadata=c.metadata)
        for c, s in zip(candidates, scores)
    ]
    reranked.sort(key=lambda c: c.score, reverse=True)
    return reranked[: settings.rerank_top_k]


def rerank(state: QueryState) -> dict:
    ctx = _make_ctx(state)
    cands = state["fused"]
    print(f"⭐ Reranker fused top-3:  {[c.chunk_id[:8] for c in cands[:3]]}")
    top = _rerank_impl(state["question"], cands, ctx=ctx)
    print(f"⭐ Reranker reranked top-3: {[c.chunk_id[:8] for c in top[:3]]}")

    allowed, denied_ids = live_recheck(top, state.get("user_levels"), ctx=ctx)
    log_retrieval_audit(
        user_id=state.get("tenant_id", "local"),
        query=state["question"],
        returned_ids=[c.chunk_id for c in allowed],
        denied_ids=denied_ids,
        user_levels=state.get("user_levels"),
        ctx=ctx,
    )
    return {"reranked": allowed}


@traced("generate.llm")
def _generate_impl(question: str, reranked: list[RetrievedChunk],
                   lang: str = "de",
                   step_results: list[dict] | None = None,
                   ctx: Context | None = None) -> dict:
    llm = get_llm()
    ctx_text = "\n\n".join(
        f"[{i + 1}] (p.{c.metadata['page_numbers']}) {c.content}"
        for i, c in enumerate(reranked)
    )

    if step_results:
        steps_text = "\n".join(
            f"Step {r['step']}: {r['sub_question']}\n  Result: {r['answer']}"
            for r in step_results
        )
        prompt = SYNTHESIZE_PROMPT.format(question=question, steps=steps_text, context=ctx_text, lang=lang)
    else:
        prompt = GENERATION_PROMPT.format(question=question, context=ctx_text, lang=lang)

    answer = llm.invoke(prompt)
    citations = [
        {
            "chunk_id": c.chunk_id,
            "page_numbers": c.metadata["page_numbers"],
            "section": c.metadata.get("heading_path", []),
            "bboxes": c.metadata.get("bboxes", []),
        }
        for c in reranked
    ]
    return {"answer": answer.content, "citations": citations, "context": ctx_text}


def _try_resolver(question: str, reranked: list[RetrievedChunk],
                   ctx: Context | None = None) -> dict | None:
    """Try deterministic resolution for derived-answer questions."""
    import re
    if not re.search(r"\d+\s*(?:Jahre|Jahren|years)", question, re.IGNORECASE):
        return None

    try:
        from rag.capabilities.resolve import resolve_chain
        from rag.models import Computation, ComputationStep, RuleArtifact

        rules_path = "data/progression_rules.json"
        import os
        if not os.path.exists(rules_path):
            return None

        import json as _json
        with open(rules_path) as f:
            rule_data = _json.load(f)

        rules = []
        for rd in rule_data:
            comp_data = rd.get("computation")
            if not comp_data:
                continue
            comp = Computation(
                type=comp_data["type"],
                steps=[ComputationStep(**s) for s in comp_data.get("steps", [])],
                scope=comp_data.get("scope", {}),
            )
            rules.append(RuleArtifact(
                rule_kind="progression",
                statement=rd.get("statement", ""),
                consequence="Stufe",
                variables=rd.get("variables", []),
                domain="TV-L",
                source_doc_id=rd.get("chunk_id", ""),
                source_page=32,
                source_chunk_id=rd.get("chunk_id", ""),
                source_quote="§16 TV-L Stufenlaufzeit",
                confidence=0.95,
                computation=comp,
            ))

        if not rules:
            return None

        def table_lookup(grade: str, stufe: str) -> str | None:
            grade_compact = grade.replace(" ", "")
            stufe_num = re.search(r"\d+", stufe)
            stufe_n = stufe_num.group() if stufe_num else ""
            for c in reranked:
                content = c.content
                if (grade in content or grade_compact in content) and f"Stufe {stufe_n}" in content:
                    amount_match = re.search(r"(\d{1,2}\.\d{3},\d{2})\s*€", content)
                    if amount_match:
                        return amount_match.group(1) + " €"
            return None

        result = resolve_chain(question, rules, table_lookup_fn=table_lookup, ctx=ctx)
        if result.resolved:
            return {
                "resolver_value": result.value,
                "resolver_steps": result.intermediate_steps,
                "resolver_citations": result.cited_rules,
                "resolver_confidence": result.confidence,
            }
    except Exception as e:
        print(f"  ⚠️ Resolver error: {e}")

    return None


def generate(state: QueryState) -> dict:
    ctx = _make_ctx(state)
    lang = state.get("lang", "de")

    resolver_result = _try_resolver(state["question"], state["reranked"], ctx=ctx)
    if resolver_result:
        val = resolver_result["resolver_value"]
        conf = resolver_result["resolver_confidence"]
        print(f"  🧮 Resolver: {val} ({conf})")

        citations_from_resolver = []
        for c in resolver_result.get("resolver_citations", []):
            if "source_quote" in c:
                citations_from_resolver.append(f"  - {c['source_quote']} (S. {c.get('page', '?')})")
            elif "table_lookup" in c:
                citations_from_resolver.append(f"  - Tabelle: {c['table_lookup']} = {c.get('amount', '?')}")

        resolver_prompt = (
            f"DETERMINISTIC COMPUTATION RESULT (verified, use this as the answer):\n"
            f"  {val}\n"
            f"Sources:\n" + "\n".join(citations_from_resolver) + "\n\n"
            f"Present this result in {{lang}}. Do NOT compute a different number. "
            f"Cite the step rules used."
        )

        llm = get_llm()
        prompt = (
            f"You are an assistant for tariff/HR documents (TV-L).\n"
            f"Answer EXCLUSIVELY in this language (ISO code): {lang}.\n\n"
            f"{resolver_prompt.format(lang=lang)}\n\n"
            f"Question: {state['question']}\n\n"
            f"Reminder: respond ONLY in {lang}. Use the computed result above as your answer."
        )
        answer = llm.invoke(prompt)

        citations = [
            {"chunk_id": c.chunk_id, "page_numbers": c.metadata["page_numbers"],
             "section": c.metadata.get("heading_path", []),
             "bboxes": c.metadata.get("bboxes", [])}
            for c in state["reranked"][:5]
        ]
        return {"answer": answer.content, "citations": citations, "context": val}

    return _generate_impl(
        state["question"], state["reranked"],
        lang=lang, step_results=state.get("step_results"), ctx=ctx,
    )


# ── Graph ────────────────────────────────────────────────────────────────

def build_query_graph():
    g = StateGraph(QueryState)
    g.add_node("transform_query", transform_query)
    g.add_node("retrieve_dense", retrieve_dense)
    g.add_node("retrieve_sparse", retrieve_sparse)
    g.add_node("retrieve_graph", retrieve_graph)
    g.add_node("rrf_fuse", rrf_fuse)
    g.add_node("rerank", rerank)
    g.add_node("generate", generate)

    g.add_edge(START, "transform_query")
    g.add_edge("transform_query", "retrieve_dense")
    g.add_edge("transform_query", "retrieve_sparse")
    g.add_edge("transform_query", "retrieve_graph")
    g.add_edge("retrieve_dense", "rrf_fuse")
    g.add_edge("retrieve_sparse", "rrf_fuse")
    g.add_edge("retrieve_graph", "rrf_fuse")
    g.add_edge("rrf_fuse", "rerank")
    g.add_edge("rerank", "generate")
    g.add_edge("generate", END)

    return g.compile()
