"""Ingestion pipeline: PDF → Docling → chunks → dense+sparse embeddings → Qdrant."""

import atexit
import hashlib
import uuid
from itertools import islice
from pathlib import Path
from typing import NotRequired, TypedDict

from docling.chunking import HybridChunker
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel
from langgraph.graph import END, START, StateGraph

from convert_pdf import convert as convert_pdf
from rag.config import settings
from rag.llm.provider import get_embedder, get_sparse_embedder
from rag.models import BBox, ChunkRecord, DocumentMeta
from rag.storage.document_store import SQLiteDocumentStore
from rag.storage.vector_store import QdrantVectorStore

_doc_store = None
_vec_store = None


def _cleanup():
    global _vec_store
    if _vec_store is not None:
        _vec_store.client.close()
        _vec_store = None


atexit.register(_cleanup)


def _get_doc_store() -> SQLiteDocumentStore:
    global _doc_store
    if _doc_store is None:
        _doc_store = SQLiteDocumentStore()
    return _doc_store


def _get_vec_store() -> QdrantVectorStore:
    global _vec_store
    if _vec_store is None:
        _vec_store = QdrantVectorStore()
    return _vec_store


class IngestionState(TypedDict):
    file_path: str
    doc_version: NotRequired[str]
    doc_meta: NotRequired[DocumentMeta]
    docling_path: NotRequired[str]
    indexed_count: NotRequired[int]
    status: NotRequired[str]
    error: NotRequired[str]


def _content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def _extract_bboxes(chunk_meta, doc: DoclingDocument) -> list[BBox]:
    bboxes = []
    for item in chunk_meta.doc_items:
        for prov in item.prov:
            bb = prov.bbox
            page_height = doc.pages[prov.page_no].size.height if prov.page_no in doc.pages else 0.0
            if bb.coord_origin.value == "BOTTOMLEFT":
                bboxes.append(BBox(
                    page=prov.page_no,
                    x=bb.l,
                    y=page_height - bb.t,
                    width=bb.r - bb.l,
                    height=abs(bb.t - bb.b),
                ))
            else:
                bboxes.append(BBox(
                    page=prov.page_no,
                    x=bb.l,
                    y=bb.t,
                    width=bb.r - bb.l,
                    height=abs(bb.b - bb.t),
                ))
    return bboxes


def _chunk_type(chunk_meta) -> str:
    for item in chunk_meta.doc_items:
        if item.label == DocItemLabel.TABLE:
            return "table"
    return "text"


def _page_numbers(chunk_meta) -> list[int]:
    pages = set()
    for item in chunk_meta.doc_items:
        for prov in item.prov:
            pages.add(prov.page_no)
    return sorted(pages)


def _batched(iterable, n):
    it = iter(iterable)
    while True:
        batch = list(islice(it, n))
        if not batch:
            break
        yield batch


# ── Nodes ────────────────────────────────────────────────────────────────

def convert(state: IngestionState) -> dict:
    file_path = Path(state["file_path"])
    if not file_path.exists():
        return {"status": "error", "error": f"File not found: {file_path}"}

    content_hash = _content_hash(file_path)
    doc_store = _get_doc_store()

    if doc_store.exists(content_hash):
        print(f"⏭️  {file_path.name}: skipped (duplicate)")
        return {"status": "skipped (duplicate)"}

    docling_path, _ = convert_pdf(file_path)

    doc = DoclingDocument.load_from_json(docling_path)
    num_pages = len(doc.pages)

    doc_id = str(uuid.uuid4())

    old_doc_id = doc_store.find_current_by_filename(file_path.name)
    if old_doc_id:
        doc_store.mark_superseded(old_doc_id, doc_id)
        print(f"🔄 Superseded old version (doc_id={old_doc_id[:8]}…)")

    meta = DocumentMeta(
        doc_id=doc_id,
        filename=file_path.name,
        content_hash=content_hash,
        num_pages=num_pages,
        doc_version=state.get("doc_version"),
    )

    doc_store.register(meta)
    print(f"📄 Registered {file_path.name} (doc_id={doc_id[:8]}…, {num_pages} pages)")
    return {"doc_meta": meta, "docling_path": str(docling_path), "status": "converted"}


def chunk_and_index(state: IngestionState) -> dict:
    if state.get("status") != "converted":
        return {"status": state.get("status", "skipped")}

    meta = state["doc_meta"]
    docling_path = Path(state["docling_path"])

    doc = DoclingDocument.load_from_json(docling_path)

    chunker = HybridChunker(
        max_tokens=settings.max_chunk_tokens,
        merge_peers=True,
    )
    chunks_iter = chunker.chunk(doc)

    embedder = get_embedder()
    sparse_embedder = get_sparse_embedder()

    vec_store = _get_vec_store()
    test_dim = len(list(embedder.embed(["dim"]))[0])
    vec_store.ensure_collection(dense_dim=test_dim)

    total = 0
    for batch in _batched(chunks_iter, settings.chunk_batch_size):
        records = []
        texts = []
        for chunk in batch:
            chunk_id = str(uuid.uuid4())
            records.append(ChunkRecord(
                chunk_id=chunk_id,
                type=_chunk_type(chunk.meta),
                content=chunk.text,
                source_file=meta.filename,
                doc_id=meta.doc_id,
                doc_version=meta.doc_version,
                page_numbers=_page_numbers(chunk.meta),
                heading_path=chunk.meta.headings or [],
                bboxes=_extract_bboxes(chunk.meta, doc),
            ))
            texts.append(chunk.text)

        dense_vecs = [v.tolist() for v in embedder.embed(texts)]
        sparse_vecs = [
            {"indices": sv.indices.tolist(), "values": sv.values.tolist()}
            for sv in sparse_embedder.embed(texts)
        ]

        vec_store.upsert(records, dense_vecs, sparse_vecs)
        total += len(batch)
        print(f"  Indexed batch: {len(batch)} chunks (total: {total})")

    print(f"✅ Indexed {total} chunks")
    return {"indexed_count": total, "status": "done"}


# ── Graph ────────────────────────────────────────────────────────────────

def build_ingestion_graph():
    g = StateGraph(IngestionState)
    g.add_node("convert", convert)
    g.add_node("chunk_and_index", chunk_and_index)
    g.add_edge(START, "convert")
    g.add_edge("convert", "chunk_and_index")
    g.add_edge("chunk_and_index", END)
    return g.compile()
