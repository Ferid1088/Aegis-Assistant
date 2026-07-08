import threading

from qdrant_client import QdrantClient, models as qm

from rag.config import settings
from rag.domain.models import ChunkRecord, RetrievedChunk
from rag.infra.stores.base import VectorStore


class QdrantVectorStore(VectorStore):
    """A note on process-wide sharing: embedded/local Qdrant storage
    (QdrantClient(path=...), used throughout this project -- there's no separate
    Qdrant server) takes an exclusive, portalocker-based lock on the storage
    directory for as long as any QdrantClient instance pointed at it stays open.
    A second, independent QdrantClient(path=same_path) opened from the SAME
    process while the first is still open raises RuntimeError("Storage folder
    ... is already accessed by another instance..."), even for purely
    sequential (non-concurrent) use -- the lock is tied to the open handle, not
    to actual concurrent access. Use get_shared_vector_store() below (not
    QdrantVectorStore() directly) from any code that might run in the same
    process as other Qdrant-touching code, to guarantee only one handle is ever
    open per process."""

    def __init__(self) -> None:
        if settings.qdrant_url:
            self.client = QdrantClient(url=settings.qdrant_url)
        else:
            self.client = QdrantClient(path=settings.qdrant_path)
        self.collection = settings.qdrant_collection

    def ensure_collection(self, dense_dim: int) -> None:
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            self.collection,
            vectors_config={
                "dense": qm.VectorParams(
                    size=dense_dim,
                    distance=qm.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": qm.SparseVectorParams(),
            },
        )

    def upsert(
        self,
        records: list[ChunkRecord],
        dense: list[list[float]],
        sparse: list[dict],
    ) -> None:
        points = []
        for rec, d_vec, s_vec in zip(records, dense, sparse):
            points.append(
                qm.PointStruct(
                    id=rec.chunk_id,
                    vector={
                        "dense": d_vec,
                        "sparse": qm.SparseVector(
                            indices=s_vec["indices"],
                            values=s_vec["values"],
                        ),
                    },
                    payload={
                        "chunk_id": rec.chunk_id,
                        "type": rec.type,
                        "content": rec.content,
                        "source_file": rec.source_file,
                        "doc_id": rec.doc_id,
                        "doc_version": rec.doc_version,
                        "page_numbers": rec.page_numbers,
                        "heading_path": rec.heading_path,
                        "bboxes": [b.model_dump() for b in rec.bboxes],
                        "keywords": rec.keywords,
                        "summary": rec.summary,
                        "value_num": rec.value_num,
                        "tenant_id": rec.tenant_id,
                        "acl_levels": rec.acl_levels,
                        "document_type": rec.document_type,
                        "logical_doc_id": rec.logical_doc_id,
                        "is_current": rec.is_current,
                    },
                )
            )
        self.client.upsert(self.collection, points)

    def search_dense(
        self,
        vec: list[float],
        k: int,
        flt: dict | None = None,
    ) -> list[RetrievedChunk]:
        results = self.client.query_points(
            collection_name=self.collection,
            query=vec,
            using="dense",
            limit=k,
            query_filter=self._build_filter(flt) if flt else None,
            with_payload=True,
        ).points
        return [self._to_retrieved(hit) for hit in results]

    def search_sparse(
        self,
        vec: dict,
        k: int,
        flt: dict | None = None,
    ) -> list[RetrievedChunk]:
        results = self.client.query_points(
            collection_name=self.collection,
            query=qm.SparseVector(indices=vec["indices"], values=vec["values"]),
            using="sparse",
            limit=k,
            query_filter=self._build_filter(flt) if flt else None,
            with_payload=True,
        ).points
        return [self._to_retrieved(hit) for hit in results]

    @staticmethod
    def _to_retrieved(hit) -> RetrievedChunk:
        payload = hit.payload or {}
        return RetrievedChunk(
            chunk_id=payload.get("chunk_id", str(hit.id)),
            content=payload.get("content", ""),
            score=hit.score if hit.score is not None else 0.0,
            metadata=payload,
        )

    @staticmethod
    def _build_filter(flt: dict) -> qm.Filter:
        if flt.get("_acl_deny_all"):
            return qm.Filter(must=[
                qm.FieldCondition(key="chunk_id", match=qm.MatchValue(value="__impossible__"))
            ])

        conditions = []
        for key, value in flt.items():
            if key == "acl_levels_any":
                conditions.append(
                    qm.FieldCondition(key="acl_levels", match=qm.MatchAny(any=value))
                )
            elif key == "document_type_any":
                conditions.append(qm.Filter(should=[
                    qm.FieldCondition(key="document_type", match=qm.MatchAny(any=value)),
                    qm.IsNullCondition(is_null=qm.PayloadField(key="document_type")),
                ]))
            else:
                conditions.append(
                    qm.FieldCondition(key=key, match=qm.MatchValue(value=value))
                )
        return qm.Filter(must=conditions)


_shared_vec_store: QdrantVectorStore | None = None
_shared_vec_store_lock = threading.Lock()


def get_shared_vector_store() -> QdrantVectorStore:
    """Process-wide QdrantVectorStore singleton.

    rag/pipelines/ingestion/nodes.py (writes, during ingestion) and
    rag/capabilities/search/search_service.SearchService (reads, during
    retrieval) used to each lazily create and cache their OWN separate
    QdrantVectorStore -- fine as long as a process only ever did ingestion OR
    querying, but broken the moment a single process does both: the embedded
    Qdrant storage only allows one open handle at a time (see the class
    docstring above), so the second, independently-created client collides
    with the first, still-open one. Reproduced by
    tests/integration/test_upload_and_chat_flow.py, which -- by design, via
    Celery's eager/synchronous mode, specifically so no separate worker
    process is needed -- runs a real ingestion and then a real chat query in
    one process: RuntimeError("Storage folder ./data/qdrant is already
    accessed by another instance of Qdrant client...").

    Guarded by a real lock (not a bare `if _shared_vec_store is None` check):
    rag/graphs/query.py's retrieval nodes (dense/sparse/graph) run concurrently
    across worker threads within a single query (LangGraph fans them out via a
    thread pool executor), so the very first call into this function during a
    query can race across threads. Confirmed real and non-deterministic --
    reproduced independently of any CI/act artifact by running
    tests/integration/test_upload_and_chat_flow.py repeatedly on the real local
    host: two threads both saw `_shared_vec_store is None`, both tried to open
    the exclusively-locked embedded Qdrant storage, and the loser raised
    RuntimeError instead of reusing the winner's client -- a plain
    double-checked-locking bug (check-then-set with no synchronization).
    """
    global _shared_vec_store
    if _shared_vec_store is None:
        with _shared_vec_store_lock:
            if _shared_vec_store is None:
                _shared_vec_store = QdrantVectorStore()
    return _shared_vec_store


def close_shared_vector_store() -> None:
    global _shared_vec_store
    if _shared_vec_store is not None:
        _shared_vec_store.client.close()
        _shared_vec_store = None
