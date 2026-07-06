"""Query pipeline: question → transform → dense+sparse+graph retrieval → RRF → rerank → generate.

Nodes are THIN: read state → call capability → write state.
Search goes through capabilities/search/SearchService. Extraction through capabilities/extract.
"""

import json
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import InMemorySaver
from sentence_transformers import CrossEncoder

from rag.capabilities.answerability import (
    check_structural_coherence,
    check_temporal_guard,
    classify,
    load_candidate_rules,
)
from rag.capabilities.contextualize import contextualize_question, normalize_question
from rag.capabilities.search.search_service import SearchService
from rag.config import settings
from rag.crosscutting.context import Context
import rag.crosscutting.observability.tracing as _tracing
from rag.crosscutting.observability.tracing import traced
from rag.crosscutting.security.acl import acl_filter, live_recheck, log_retrieval_audit, type_filter
from rag.llm.provider import get_device, get_llm
from rag.models import RetrievedChunk
from rag.storage.vector_store import get_shared_vector_store


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
        # query-side singleton and rag/graphs/ingestion.py's write-side singleton
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


def _trim_cache(cache: dict) -> dict:
    items = list(cache.items())[-_MAX_CACHE_ENTRIES:]
    return dict(items)


# ── Prompts ──────────────────────────────────────────────────────────────

TRANSFORM_PROMPT = """\
You are a search query optimizer for document-grounded retrieval across legal, HR, policy,
and technical documents.
Given a user question, produce a JSON object with four fields:
- "rewritten": the question rewritten with precise document-domain terminology for dense vector search
- "expanded": the question expanded with close synonyms and related terms for sparse keyword search
- "entities": a list of key entity names mentioned or implied (for graph lookup)
- "lang": the ISO 639-1 code of the language the QUESTION SENTENCE is written in (e.g. "de", "en"). \
Judge by the sentence grammar and function words (what/was/wie/welche), NOT by domain terms like \
codes, table labels, or section markers that may stay unchanged across languages.

Rules:
- Output ONLY valid JSON, no explanation.
- Keep rewritten and expanded in the same language as the user's question unless the
  question itself explicitly targets a term in another language.
- entities should use canonical terms from the document/question language.
- "lang": detect from the QUESTION sentence structure, not domain vocabulary.

Question: {question}
"""

GENERATION_PROMPT = """\
You are an assistant for document-grounded question answering.
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
You are an assistant for document-grounded question answering.
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


HYDE_PROMPT = """\
Write a short document passage in {lang} that would directly answer the following question.
Use plausible domain language. Do NOT say you don't know.

Question: {question}
"""

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

def contextualize(state: QueryState) -> dict:
    import json as _json
    import time as _time
    from rag.capabilities.cache import read_cache

    raw_question = state["question"]
    history = state.get("turn_history", [])
    result = contextualize_question(raw_question, history)
    standalone = result.standalone_question.strip() or raw_question
    normalized = normalize_question(standalone)

    # L1: in-memory per-session cache (with TTL check)
    cached_mem_raw = dict(state.get("repeat_cache", {})).get(normalized)
    if cached_mem_raw:
        age = _time.time() - cached_mem_raw.get("ts", 0)
        if age > settings.cache_ttl_answer:
            cached_mem_raw = None
    cached_mem = {k: v for k, v in cached_mem_raw.items() if k != "ts"} if cached_mem_raw else None

    # L2: Redis cross-session answer cache (key includes doc_filter)
    cached_redis = None
    if not cached_mem:
        _doc_filter_str = _json.dumps(state.get("doc_filter") or {}, sort_keys=True)
        _redis_key = normalized + "|" + _doc_filter_str
        cached_redis = read_cache("answer", _redis_key)

    cached = cached_mem or cached_redis

    payload = {
        "raw_question": raw_question,
        "question": standalone,
        "standalone_question": standalone,
        "normalized_question": normalized,
        "cache_hit": bool(cached),
        "was_contextualized": result.was_contextualized,
        "is_followup": result.is_followup,
    }
    if cached:
        payload.update({
            "cached_answer": cached.get("answer", ""),
            "cached_citations": cached.get("citations", []),
            "cached_context": cached.get("context", ""),
            "response_source": "cache",
        })
    return payload


def _route_after_contextualize(state: QueryState) -> str:
    return "cached_response" if state.get("cache_hit") else "transform_query"


def cached_response(state: QueryState) -> dict:
    return {
        "answer": state.get("cached_answer", ""),
        "citations": state.get("cached_citations", []),
        "context": state.get("cached_context", ""),
        "response_source": "cache",
    }

def transform_query(state: QueryState) -> dict:
    from rag.capabilities.cache import cached
    from rag.config import settings as _s

    question = state["question"]

    def _call_llm():
        llm = get_llm()
        prompt = TRANSFORM_PROMPT.format(question=question)
        response = llm.invoke(prompt)
        try:
            text = response.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(text)
            return {
                "rewritten": parsed.get("rewritten", question),
                "expanded": parsed.get("expanded", question),
                "lang": parsed.get("lang", "de"),
            }
        except (json.JSONDecodeError, AttributeError, IndexError):
            return {"rewritten": question, "expanded": question, "lang": "de"}

    result = cached("transform", question, _s.cache_ttl_transform, _call_llm)
    rewritten = result["rewritten"]
    expanded = result["expanded"]
    lang = result["lang"]

    heuristic_lang = _detect_lang_heuristic(question)
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
    if settings.version_filter:
        flt["is_current"] = True
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


def maybe_hyde(state: QueryState) -> dict:
    """Expand fused results with HyDE when retrieval confidence is low."""
    if not settings.hyde_enabled:
        return {}

    fused = state.get("fused", [])
    # NOTE: fused[0].score is the original per-retriever score (dense cosine, sparse BM25,
    # or hardcoded 0.5 for graph hits) — NOT a normalized RRF fused score.
    # Hyde threshold tuning should account for this; dense results typically score 0.0-1.0.
    top_score = fused[0].score if fused else 0.0
    if top_score >= settings.hyde_threshold:
        return {}

    print(f"🔮 HyDE triggered (top score {top_score:.3f} < {settings.hyde_threshold})")
    llm = get_llm()
    lang = state.get("lang", "de")
    hyp = llm.invoke(HYDE_PROMPT.format(question=state["question"], lang=lang))

    search = _get_search()
    ctx = _make_ctx(state)
    flt = _build_retrieval_filter(state)
    hyde_hits = search.search_dense(hyp.content, flt=flt, ctx=ctx)

    merged = SearchService.rrf([fused, hyde_hits], k=settings.rrf_k, ctx=ctx)
    print(f"🔮 HyDE added {len(hyde_hits)} hits → merged to {len(merged)}")
    return {"fused": merged[: settings.fusion_candidates]}


@traced("rerank.cross_encoder")
def _rerank_impl(question: str, candidates: list[RetrievedChunk],
                 ctx: Context | None = None) -> list[RetrievedChunk]:
    if not candidates:
        return []
    pairs = [[question, c.content] for c in candidates]
    scores = _get_reranker().predict(pairs, batch_size=settings.reranker_batch_size)
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


def check_answerability(state: QueryState) -> dict:
    ctx = _make_ctx(state)
    result = classify(state["question"], state.get("reranked", []), ctx=ctx)
    return {
        "answerability_verdict": result.verdict,
        "assumptions": result.assumptions,
        "clarification_question": result.clarification_question,
        "unanswerable_reason": result.unanswerable_reason,
        "gate_candidate_rules": result.gate_candidate_rules,
    }


def _route_answerability(state: QueryState) -> str:
    verdict = state.get("answerability_verdict", "unanswerable")
    if verdict in {"answerable", "assumption"}:
        return "generate"
    return "gate_response"


def gate_response(state: QueryState) -> dict:
    verdict = state.get("answerability_verdict", "unanswerable")
    if verdict == "clarification":
        answer = state.get("clarification_question") or "Ich brauche noch eine genauere Angabe, bevor ich sicher antworten kann."
    else:
        answer = state.get("unanswerable_reason") or "Ich kann diese Frage mit den vorhandenen Regeln und Belegen derzeit nicht verlässlich beantworten."
    return {"answer": answer, "citations": [], "context": "", "response_source": "gate"}


def finalize_turn(state: QueryState) -> dict:
    import json as _json
    import hashlib as _hashlib
    import time as _time
    from rag.config import settings as _s

    history = list(state.get("turn_history", []))
    history.append({
        "user_question": state.get("raw_question", state["question"]),
        "standalone_question": state.get("standalone_question", state["question"]),
        "answer": state.get("answer", ""),
        "answerability_verdict": state.get("answerability_verdict"),
        "response_source": state.get("response_source", "pipeline"),
        "was_contextualized": state.get("was_contextualized", False),
    })
    history = history[-_MAX_TURNS:]

    cache = dict(state.get("repeat_cache", {}))
    normalized = state.get("normalized_question")
    answer = state.get("answer", "")
    if normalized and answer:
        entry = {
            "answer": answer,
            "citations": state.get("citations", []),
            "context": state.get("context", ""),
            "ts": _time.time(),
        }
        cache[normalized] = entry
        cache = _trim_cache(cache)

        # L2: persist to Redis answer cache
        # Skip L2 cache write for gate refusals — don't cache "I can't answer" cross-session
        if state.get("response_source") != "gate":
            try:
                from rag.capabilities.cache import get_redis
                _r = get_redis()
                if _r is not None:
                    _doc_filter_str = _json.dumps(state.get("doc_filter") or {}, sort_keys=True)
                    _redis_key = normalized + "|" + _doc_filter_str
                    _hashed = _hashlib.sha256(_redis_key.encode()).hexdigest()
                    _redis_entry = {k: v for k, v in entry.items() if k != "ts"}
                    _r.setex(f"answer:{_hashed}", _s.cache_ttl_answer, _json.dumps(_redis_entry))
            except Exception as exc:
                import logging as _logging
                _logging.getLogger(__name__).warning("Redis answer write failed (%s) — skipping", exc)

    return {
        "turn_history": history,
        "repeat_cache": cache,
    }


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

    # Record behavior outcome on this span — no pipeline logic change.
    _declined_phrases = ("nicht ableitbar", "not found", "nicht im kontext",
                         "cannot answer", "keine information", "nicht enthalten",
                         "is not in the context", "not in the provided")
    answer_lower = answer.content.lower()
    if step_results:
        outcome = "fallback"
    elif any(p in answer_lower for p in _declined_phrases):
        outcome = "declined"
    else:
        outcome = "answered"
    _tracing.set_span_attribute("outcome", outcome)
    if not reranked:
        _tracing.set_span_attribute("retrieval_miss", True)

    return {"answer": answer.content, "citations": citations, "context": ctx_text}


def _try_resolver(question: str, reranked: list[RetrievedChunk],
                   ctx: Context | None = None) -> dict | None:
    """Try deterministic resolution for derived-answer questions."""
    import re
    if not re.search(r"\d+\s*(?:Jahre|Jahren|years)", question, re.IGNORECASE):
        return None

    try:
        from rag.capabilities.resolve import resolve_chain
        rules = load_candidate_rules()

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
                "resolver_formatted": result.formatted,
                "resolver_unit": result.unit,
                "resolver_steps": result.intermediate_steps,
                "resolver_citations": result.cited_rules,
                "resolver_confidence": result.confidence,
                "resolver_source_rules": result.source_rules,
            }
    except Exception as e:
        print(f"  ⚠️ Resolver error: {e}")

    return None


def generate(state: QueryState) -> dict:
    ctx = _make_ctx(state)
    lang = state.get("lang", "de")
    assumptions = state.get("assumptions", [])

    resolver_result = _try_resolver(state["question"], state["reranked"], ctx=ctx)
    if resolver_result:
        temporal_issue = check_temporal_guard(state["question"], resolver_result, state["reranked"])
        if temporal_issue:
            stage = temporal_issue.get("stage")
            partial = f" Ich kann aber noch {stage} aus den Regeln ableiten." if stage else ""
            return {
                "answer": f"Ich kann das aktuelle Entgelt nicht verlässlich beantworten. {temporal_issue['reason']}{partial}",
                "citations": [],
                "context": "",
            }

        coherence_issue = check_structural_coherence(state["question"], resolver_result, state["reranked"])
        if coherence_issue:
            return {
                "answer": f"Ich beantworte das lieber nicht direkt, weil die Belege bzw. Berechnung widersprüchlich sind: {coherence_issue['reason']}",
                "citations": [],
                "context": "",
            }

        val = resolver_result.get("resolver_formatted") or str(resolver_result["resolver_value"])
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
            f"You are an assistant for document-grounded question answering.\n"
            f"Answer EXCLUSIVELY in this language (ISO code): {lang}.\n\n"
            f"{resolver_prompt.format(lang=lang)}\n\n"
            f"Question: {state['question']}\n\n"
            f"Reminder: respond ONLY in {lang}. Use the computed result above as your answer."
        )
        answer = llm.invoke(prompt)
        final_answer = answer.content
        if assumptions:
            final_answer = "\n".join([*assumptions, "", final_answer])

        citations = [
            {"chunk_id": c.chunk_id, "page_numbers": c.metadata["page_numbers"],
             "section": c.metadata.get("heading_path", []),
             "bboxes": c.metadata.get("bboxes", [])}
            for c in state["reranked"][:5]
        ]
        return {"answer": final_answer, "citations": citations, "context": val}

    generated = _generate_impl(
        state["question"], state["reranked"],
        lang=lang, step_results=state.get("step_results"), ctx=ctx,
    )
    if assumptions:
        generated["answer"] = "\n".join([*assumptions, "", generated["answer"]])
    generated["response_source"] = "pipeline"
    return generated


# ── Lifecycle gate ───────────────────────────────────────────────────────

def lifecycle_gate(state: QueryState) -> dict:
    from rag.crosscutting.security.authorize import _state_blocked_actions
    conv_state = (state.get("conversation_state") or "active").lower()
    blocked = "search" in _state_blocked_actions(conv_state)
    return {"lifecycle_blocked": blocked}


def _route_after_lifecycle(state: QueryState) -> str:
    return "lifecycle_denied" if state.get("lifecycle_blocked") else "contextualize"


def lifecycle_denied(state: QueryState) -> dict:
    conv_state = (state.get("conversation_state") or "").lower()
    _MSG = {
        "soft_deleted": "Diese Konversation wurde gelöscht und ist für Abfragen gesperrt.",
        "purged": "Diese Konversation wurde endgültig gelöscht.",
    }
    msg = _MSG.get(conv_state, f"Konversation nicht verfügbar (Status: {conv_state or 'unbekannt'}).")
    return {"answer": msg, "citations": [], "context": "", "response_source": "lifecycle_blocked"}


# ── Graph ────────────────────────────────────────────────────────────────

def build_query_graph():
    g = StateGraph(QueryState)
    g.add_node("lifecycle_gate", lifecycle_gate)
    g.add_node("lifecycle_denied", lifecycle_denied)
    g.add_node("contextualize", contextualize)
    g.add_node("cached_response", cached_response)
    g.add_node("transform_query", transform_query)
    g.add_node("retrieve_dense", retrieve_dense)
    g.add_node("retrieve_sparse", retrieve_sparse)
    g.add_node("retrieve_graph", retrieve_graph)
    g.add_node("rrf_fuse", rrf_fuse)
    g.add_node("maybe_hyde", maybe_hyde)
    g.add_node("rerank", rerank)
    g.add_node("check_answerability", check_answerability)
    g.add_node("gate_response", gate_response)
    g.add_node("generate", generate)
    g.add_node("finalize_turn", finalize_turn)

    g.add_edge(START, "lifecycle_gate")
    g.add_conditional_edges(
        "lifecycle_gate",
        _route_after_lifecycle,
        {"contextualize": "contextualize", "lifecycle_denied": "lifecycle_denied"},
    )
    g.add_edge("lifecycle_denied", END)
    g.add_conditional_edges(
        "contextualize",
        _route_after_contextualize,
        {
            "cached_response": "cached_response",
            "transform_query": "transform_query",
        },
    )
    g.add_edge("transform_query", "retrieve_dense")
    g.add_edge("transform_query", "retrieve_sparse")
    g.add_edge("transform_query", "retrieve_graph")
    g.add_edge("retrieve_dense", "rrf_fuse")
    g.add_edge("retrieve_sparse", "rrf_fuse")
    g.add_edge("retrieve_graph", "rrf_fuse")
    g.add_edge("rrf_fuse", "maybe_hyde")
    g.add_edge("maybe_hyde", "rerank")
    g.add_edge("rerank", "check_answerability")
    g.add_conditional_edges(
        "check_answerability",
        _route_answerability,
        {
            "generate": "generate",
            "gate_response": "gate_response",
        },
    )
    g.add_edge("generate", "finalize_turn")
    g.add_edge("gate_response", "finalize_turn")
    g.add_edge("cached_response", "finalize_turn")
    g.add_edge("finalize_turn", END)

    return g.compile(checkpointer=_checkpointer)
