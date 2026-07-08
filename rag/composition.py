"""Composition root — discoverability index of the app's constructed dependencies.

This is a re-export aggregator, not a lifecycle-changing composition root: every
name below is the literal same function as in its source module, imported here
unchanged. None of them are called at import time, and none of their laziness,
caching, or rebuild semantics change by being re-exported — get_engine() is still
lazily rebuilt after install.py mutates settings.database_url (Phase 8.10b),
get_shared_vector_store() is still a process-wide singleton avoiding the Qdrant
file-lock race between ingestion and query (Phase 8.8), and the embedder/reranker/
LLM getters still defer loading multi-GB models until first called.

Existing call sites are NOT required to import from here — they keep importing
directly from each function's home module. This file exists so a developer (or a
new call site) has one place to see everything the app constructs, not to force
a migration of ~20+ existing import sites.

Edition wiring (Starter/Ollama vs Enterprise/vLLM) happens in
rag.infra.models.llm._make_chat, branching on settings.llm_backend — that
function backs both get_llm() and get_extraction_llm() below.
"""

# Models (embedding, sparse, LLM) — rag/infra/models/llm.py
from rag.infra.models.llm import (
    get_device,
    get_embedder,
    get_sparse_embedder,
    get_llm,
    get_extraction_llm,
)

# Vector store — rag/infra/stores/vector_store.py
from rag.infra.stores.vector_store import (
    get_shared_vector_store,
    close_shared_vector_store,
)

# SQL engine/session — rag/infra/stores/sql/base.py
from rag.infra.stores.sql.base import (
    get_engine,
    reset_engine,
    get_db,
    SessionLocal,
)

# Cache — rag/capabilities/cache.py
from rag.capabilities.cache import get_redis

# Observability trace store — rag/crosscutting/observability/trace_store.py
from rag.crosscutting.observability.trace_store import get_trace_store

__all__ = [
    "get_device",
    "get_embedder",
    "get_sparse_embedder",
    "get_llm",
    "get_extraction_llm",
    "get_shared_vector_store",
    "close_shared_vector_store",
    "get_engine",
    "reset_engine",
    "get_db",
    "SessionLocal",
    "get_redis",
    "get_trace_store",
]
