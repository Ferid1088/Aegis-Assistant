"""SearchService — THE shared search capability used by BOTH pipelines.

Ingestion calls it for dedup/entity normalization. Retrieval calls it for query serving.
Both get the same instrumented code paths and span names.
"""

from rag.config import settings
from rag.crosscutting.context import Context
from rag.crosscutting.observability.tracing import traced
from rag.infra.models.llm import get_embedder, get_sparse_embedder
from rag.models import RetrievedChunk
from rag.infra.stores.vector_store import QdrantVectorStore


class SearchService:
    def __init__(self, vec_store: QdrantVectorStore | None = None) -> None:
        self._vec_store = vec_store

    @property
    def vec_store(self) -> QdrantVectorStore:
        if self._vec_store is None:
            self._vec_store = QdrantVectorStore()
        return self._vec_store

    @traced("search.dense.embed")
    def embed_dense(self, texts: list[str], ctx: Context | None = None) -> list[list[float]]:
        from rag.capabilities.cache import cached
        from rag.config import settings as _s

        model = _s.dense_embedding_model
        prefix = _s.dense_query_prefix
        embedder = get_embedder()
        results = []
        for text in texts:
            key = text + "|" + model + "|" + prefix
            full_text = prefix + text if prefix else text
            vec = cached(
                "embed", key, _s.cache_ttl_embed,
                lambda t=full_text: [v.tolist() for v in embedder.embed([t])][0],
            )
            results.append(vec)
        return results

    @traced("search.sparse.embed")
    def embed_sparse(self, texts: list[str], ctx: Context | None = None) -> list[dict]:
        sparse_embedder = get_sparse_embedder()
        return [
            {"indices": sv.indices.tolist(), "values": sv.values.tolist()}
            for sv in sparse_embedder.embed(texts)
        ]

    @traced("search.dense.query")
    def search_dense(self, query: str, k: int | None = None,
                     flt: dict | None = None, ctx: Context | None = None) -> list[RetrievedChunk]:
        if k is None:
            k = settings.dense_top_k
        vecs = self.embed_dense([query], ctx=ctx)
        return self.vec_store.search_dense(vecs[0], k, flt)

    @traced("search.sparse.query")
    def search_sparse(self, query: str, k: int | None = None,
                      flt: dict | None = None, ctx: Context | None = None) -> list[RetrievedChunk]:
        if k is None:
            k = settings.sparse_top_k
        svecs = self.embed_sparse([query], ctx=ctx)
        return self.vec_store.search_sparse(svecs[0], k, flt)

    @traced("search.dense.query")
    def search_dense_multi(self, queries: list[str], k: int | None = None,
                           flt: dict | None = None, ctx: Context | None = None) -> list[list[RetrievedChunk]]:
        if k is None:
            k = settings.dense_top_k
        vecs = self.embed_dense(queries, ctx=ctx)
        return [self.vec_store.search_dense(v, k, flt) for v in vecs]

    @traced("search.sparse.query")
    def search_sparse_multi(self, queries: list[str], k: int | None = None,
                            flt: dict | None = None, ctx: Context | None = None) -> list[list[RetrievedChunk]]:
        if k is None:
            k = settings.sparse_top_k
        svecs = self.embed_sparse(queries, ctx=ctx)
        return [self.vec_store.search_sparse(sv, k, flt) for sv in svecs]

    @traced("search.graph.traverse")
    def search_graph(self, entity_names: list[str], hops: int = 2,
                     allowed_levels: list[str] | None = None,
                     ctx: Context | None = None) -> list[RetrievedChunk]:
        try:
            from rag.infra.stores.graph_store import Neo4jGraphStore
            gs = Neo4jGraphStore()
            neighbors = gs.neighbors(entity_names, hops, allowed_levels=allowed_levels)
            gs.close()
        except Exception:
            return []

        chunk_ids = list({n.get("chunk_id", "") for n in neighbors if n.get("chunk_id")})
        if not chunk_ids:
            return []

        from qdrant_client import models as qm
        pts = self.vec_store.client.scroll(
            self.vec_store.collection,
            scroll_filter=qm.Filter(must=[
                qm.FieldCondition(key="chunk_id", match=qm.MatchAny(any=chunk_ids))
            ]),
            limit=settings.graph_top_k,
            with_payload=True,
            with_vectors=False,
        )[0]

        return [
            RetrievedChunk(
                chunk_id=p.payload.get("chunk_id", str(p.id)),
                content=p.payload.get("content", ""),
                score=0.5,
                metadata=p.payload or {},
            )
            for p in pts
        ]

    @staticmethod
    @traced("search.fusion.rrf")
    def rrf(result_lists: list[list[RetrievedChunk]], k: int = 60,
            ctx: Context | None = None) -> list[RetrievedChunk]:
        scores: dict[str, float] = {}
        by_id: dict[str, RetrievedChunk] = {}
        for lst in result_lists:
            for rank, ch in enumerate(lst):
                scores[ch.chunk_id] = scores.get(ch.chunk_id, 0) + 1.0 / (k + rank)
                by_id[ch.chunk_id] = ch
        ranked = sorted(scores, key=scores.get, reverse=True)
        return [by_id[cid] for cid in ranked]

    def upsert_chunks(self, records, dense_vecs, sparse_vecs):
        self.vec_store.upsert(records, dense_vecs, sparse_vecs)
