"""Ingestion pipeline state and process-wide singletons."""

import atexit
from typing import NotRequired, TypedDict

from rag.domain.models import DocumentMeta
from rag.infra.stores.document_store import SQLiteDocumentStore
from rag.infra.stores.vector_store import QdrantVectorStore, close_shared_vector_store, get_shared_vector_store

_doc_store = None


def _cleanup():
    close_shared_vector_store()


atexit.register(_cleanup)


def _get_doc_store() -> SQLiteDocumentStore:
    global _doc_store
    if _doc_store is None:
        _doc_store = SQLiteDocumentStore()
    return _doc_store


def _get_vec_store() -> QdrantVectorStore:
    # Process-wide singleton (rag/infra/stores/vector_store.py) -- NOT a private one
    # here, so ingestion (writes) and query (reads, rag/pipelines/retrieval/) share
    # the one open embedded-Qdrant handle a process is allowed to hold. See
    # get_shared_vector_store()'s docstring for why a second, independent
    # QdrantVectorStore() used to break any process that did both.
    return get_shared_vector_store()


class IngestionState(TypedDict):
    file_path: str
    doc_version: NotRequired[str]
    doc_meta: NotRequired[DocumentMeta]
    docling_path: NotRequired[str]
    version_id: NotRequired[str]
    indexed_count: NotRequired[int]
    status: NotRequired[str]
    error: NotRequired[str]
