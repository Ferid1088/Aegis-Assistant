from abc import ABC, abstractmethod

from rag.domain.models import ChunkRecord, DocumentMeta, RetrievedChunk


class VectorStore(ABC):
    @abstractmethod
    def ensure_collection(self, dense_dim: int) -> None: ...

    @abstractmethod
    def upsert(self, records: list[ChunkRecord],
               dense: list[list[float]], sparse: list[dict]) -> None: ...

    @abstractmethod
    def search_dense(self, vec: list[float], k: int,
                     flt: dict | None = None) -> list[RetrievedChunk]: ...

    @abstractmethod
    def search_sparse(self, vec: dict, k: int,
                      flt: dict | None = None) -> list[RetrievedChunk]: ...


class DocumentStore(ABC):
    @abstractmethod
    def register(self, meta: DocumentMeta) -> bool: ...

    @abstractmethod
    def exists(self, content_hash: str) -> bool: ...

    @abstractmethod
    def mark_superseded(self, old_doc_id: str, new_doc_id: str) -> None: ...


class GraphStore(ABC):
    @abstractmethod
    def upsert_entities(self, entities: list[dict]) -> None: ...

    @abstractmethod
    def upsert_relations(self, relations: list[dict]) -> None: ...

    @abstractmethod
    def neighbors(self, entity_names: list[str], hops: int) -> list[dict]: ...
