from qdrant_client import QdrantClient, models as qm

from rag.config import settings
from rag.models import ChunkRecord, RetrievedChunk
from rag.storage.base import VectorStore


class QdrantVectorStore(VectorStore):
    def __init__(self) -> None:
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
