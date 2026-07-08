"""Ingestion pipeline: PDF → Docling → chunks → dense+sparse embeddings → Qdrant."""

import atexit
import hashlib
import json
import re
import uuid
from itertools import islice
from pathlib import Path
from typing import NotRequired, TypedDict

from docling.chunking import HybridChunker
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel
from langgraph.graph import END, START, StateGraph

from rag.convert_pdf import convert as convert_pdf
from rag.config import settings
from rag.domain.document_lifecycle import LogicalDocument, ProcessingState, resolve_identity
from rag.llm.provider import get_embedder, get_sparse_embedder
from rag.models import BBox, ChunkRecord, DocumentMeta
from rag.storage.document_store import SQLiteDocumentStore
from rag.storage.vector_store import QdrantVectorStore, close_shared_vector_store, get_shared_vector_store

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
    # Process-wide singleton (rag/storage/vector_store.py) -- NOT a private one
    # here, so ingestion (writes) and query (reads, rag/graphs/query.py) share
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


# ── Structured table helpers ─────────────────────────────────────────────

def _normalize_amount(raw: str) -> str:
    raw = raw.strip().replace("€", "").strip()
    if not raw or raw == "-":
        return ""
    parts = raw.replace(".", "").split(",")
    if len(parts) == 2:
        integer, decimal = parts
        if len(integer) > 3:
            integer = integer[:-3] + "." + integer[-3:]
        return f"{integer},{decimal} €"
    return raw + " €"


def _amount_to_float(raw: str) -> float | None:
    raw = raw.strip().replace("€", "").replace(" ", "")
    if not raw or raw == "-":
        return None
    normalized = raw.replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _grade_variants(grade: str) -> str:
    compact = grade.replace(" ", "")
    if compact != grade:
        return f"{grade} ({compact})"
    spaced = re.sub(r"([A-Za-z]+)(\d)", r"\1 \2", grade)
    if spaced != grade:
        return f"{grade} ({spaced})"
    return grade


def _detect_column_labels(first_row: list[str]) -> list[str]:
    labels = []
    for cell in first_row:
        cell = cell.strip()
        labels.append("" if cell in ("€", "") else cell)
    return labels


def _looks_like_grade_label(label: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-zÄÖÜäöü]{1,4}\s?\d+[a-zA-Z]?", label.strip()))


def _looks_like_step_label(label: str) -> bool:
    return bool(re.fullmatch(r"\d+[a-zA-Z]?", label.strip()))


def _build_row_chunk_content(row_label: str, column_label: str, amount: str) -> str:
    row_display = _grade_variants(row_label)
    if _looks_like_grade_label(row_label) and _looks_like_step_label(column_label):
        return f"Entgeltgruppe {row_display}, Stufe {column_label}: {amount}"
    return f"Zeile {row_display}, Spalte {column_label}: {amount}"


def _row_keywords(row_label: str, column_label: str) -> list[str]:
    keywords = [row_label.replace(" ", ""), row_label, column_label]
    if _looks_like_step_label(column_label):
        keywords.append(f"Stufe {column_label}")
    else:
        keywords.append(f"Spalte {column_label}")
    return keywords


def _has_structured_rows(table: dict) -> bool:
    """Any table with ≥2 rows where data rows have numeric cells gets structured."""
    if len(table["rows"]) < 2:
        return False
    for row in table["rows"][1:3]:
        if any(re.search(r"\d{3,4},\d{2}", cell) for cell in row if cell):
            return True
    return False


def _build_table_chunks(
    tables_path: Path, source_file: str, doc_id: str, doc_version: str | None,
    logical_doc_id: str | None = None,
    is_current: bool = True,
) -> list[ChunkRecord]:
    if not tables_path.exists():
        return []
    with open(tables_path) as f:
        data = json.load(f)

    chunks: list[ChunkRecord] = []
    for table in data["tables"]:
        page = table["page"]
        caption = table.get("caption", "")
        rows = table["rows"]

        if not _has_structured_rows(table):
            continue

        column_labels = _detect_column_labels(rows[0])

        for row in rows[1:]:
            grade = row[0].strip()
            if not grade or grade == "€":
                continue

            for col_idx in range(1, len(row)):
                amount_raw = row[col_idx].strip()
                if not amount_raw or amount_raw == "-":
                    continue
                if not re.search(r"\d", amount_raw):
                    continue

                column_label = column_labels[col_idx] if col_idx < len(column_labels) else str(col_idx)
                amount = _normalize_amount(amount_raw)
                value_num = _amount_to_float(amount_raw)
                if not amount:
                    continue

                content = _build_row_chunk_content(grade, column_label, amount)
                chunks.append(ChunkRecord(
                    chunk_id=str(uuid.uuid4()),
                    type="table_row",
                    content=content,
                    source_file=source_file,
                    doc_id=doc_id,
                    doc_version=doc_version,
                    page_numbers=[page],
                    heading_path=[caption] if caption else [],
                    bboxes=[],
                    keywords=_row_keywords(grade, column_label),
                    value_num=value_num,
                    logical_doc_id=logical_doc_id,
                    is_current=is_current,
                ))

        md_lines = []
        if caption:
            md_lines.append(caption)
            md_lines.append("")
        header = "| " + " | ".join(column_labels) + " |"
        md_lines.append(header)
        md_lines.append("|" + "---|" * len(column_labels))
        for row in rows[1:]:
            md_lines.append("| " + " | ".join(row) + " |")

        chunks.append(ChunkRecord(
            chunk_id=str(uuid.uuid4()),
            type="table_full",
            content="\n".join(md_lines),
            source_file=source_file,
            doc_id=doc_id,
            doc_version=doc_version,
            page_numbers=[page],
            heading_path=[caption] if caption else [],
            bboxes=[],
            logical_doc_id=logical_doc_id,
            is_current=is_current,
        ))

    return chunks


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

    doc_id = str(uuid.uuid4())

    old_doc_id = doc_store.find_current_by_filename(file_path.name)
    if old_doc_id:
        doc_store.mark_superseded(old_doc_id, doc_id)
        print(f"🔄 Superseded old version (doc_id={old_doc_id[:8]}…)")

    # ── 02.1: logical document / version split (reserved seam, dual-write) ──
    target_logical_doc_id = state.get("target_logical_doc_id")
    if target_logical_doc_id:
        logical_doc_id = target_logical_doc_id
    else:
        source_identity = resolve_identity("filesystem", path=str(file_path))
        logical_doc_id = doc_store.find_logical_by_identity(source_identity)
        if logical_doc_id is None:
            logical_doc_id = str(uuid.uuid4())
            doc_store.create_logical_document(
                LogicalDocument(logical_doc_id=logical_doc_id, source_identity=source_identity)
            )

    # We need the allocated version_id before conversion so the page-image export
    # can be written to a permanent, per-version directory instead of the staged
    # upload scratch area that gets cleaned up by the worker.
    provisional_version = doc_store.create_version(
        logical_doc_id=logical_doc_id,
        content_hash=content_hash,
        filename=file_path.name,
        num_pages=0,
    )
    render_dir = Path(settings.document_pages_dir) / provisional_version.version_id
    docling_path, _ = convert_pdf(file_path, render_dir=render_dir)

    doc = DoclingDocument.load_from_json(docling_path)
    num_pages = len(doc.pages)
    doc_store.conn.execute(
        "UPDATE document_versions SET num_pages = ?, updated_at = CURRENT_TIMESTAMP WHERE version_id = ?",
        (num_pages, provisional_version.version_id),
    )
    version = doc_store.get_versions(logical_doc_id)[-1]
    doc_store.set_processing_state(version.version_id, ProcessingState.CONVERTING)

    meta = DocumentMeta(
        doc_id=doc_id,
        filename=file_path.name,
        content_hash=content_hash,
        num_pages=num_pages,
        doc_version=state.get("doc_version"),
        logical_doc_id=logical_doc_id,
    )

    doc_store.register(meta)
    print(f"📄 Registered {file_path.name} (doc_id={doc_id[:8]}…, {num_pages} pages)")
    return {
        "doc_meta": meta,
        "docling_path": str(docling_path),
        "version_id": version.version_id,
        "status": "converted",
    }


def chunk_and_index(state: IngestionState) -> dict:
    if state.get("status") != "converted":
        return {"status": state.get("status", "skipped")}

    meta = state["doc_meta"]
    version_id = state.get("version_id")
    docling_path = Path(state["docling_path"])
    file_path = Path(state["file_path"])

    doc = DoclingDocument.load_from_json(docling_path)

    chunker = HybridChunker(
        max_tokens=settings.max_chunk_tokens,
        merge_peers=True,
    )
    chunks_iter = chunker.chunk(doc)

    embedder = get_embedder()
    sparse_embedder = get_sparse_embedder()

    vec_store = _get_vec_store()
    doc_store = _get_doc_store()
    test_dim = len(list(embedder.embed(["dim"]))[0])
    vec_store.ensure_collection(dense_dim=test_dim)

    # ── TEXT chunks (unchanged path) ─────────────────────────────────
    text_total = 0
    table_skipped = 0
    for batch in _batched(chunks_iter, settings.chunk_batch_size):
        records = []
        texts = []
        for chunk in batch:
            if _chunk_type(chunk.meta) == "table":
                table_skipped += 1
                continue

            chunk_id = str(uuid.uuid4())
            records.append(ChunkRecord(
                chunk_id=chunk_id,
                type="text",
                content=chunk.text,
                source_file=meta.filename,
                doc_id=meta.doc_id,
                doc_version=meta.doc_version,
                page_numbers=_page_numbers(chunk.meta),
                heading_path=chunk.meta.headings or [],
                bboxes=_extract_bboxes(chunk.meta, doc),
                logical_doc_id=meta.logical_doc_id,
                is_current=meta.is_current,
            ))
            texts.append(chunk.text)

        if records:
            dense_vecs = [v.tolist() for v in embedder.embed(texts, prefix=settings.dense_passage_prefix)]
            sparse_vecs = [
                {"indices": sv.indices.tolist(), "values": sv.values.tolist()}
                for sv in sparse_embedder.embed(texts)
            ]
            vec_store.upsert(records, dense_vecs, sparse_vecs)
            text_total += len(records)

    print(f"  📄 Text chunks indexed: {text_total} (skipped {table_skipped} flattened table chunks)")

    # ── TABLE chunks (structured from tables.json) ───────────────────
    tables_path = file_path.parent / f"{file_path.stem}_tables.json"
    table_chunks = _build_table_chunks(
        tables_path, meta.filename, meta.doc_id, meta.doc_version, meta.logical_doc_id,
        is_current=meta.is_current,
    )

    table_row_count = 0
    table_full_count = 0
    for batch in _batched(table_chunks, settings.chunk_batch_size):
        batch_texts = [c.content for c in batch]
        dense_vecs = [v.tolist() for v in embedder.embed(batch_texts, prefix=settings.dense_passage_prefix)]
        sparse_vecs = [
            {"indices": sv.indices.tolist(), "values": sv.values.tolist()}
            for sv in sparse_embedder.embed(batch_texts)
        ]
        vec_store.upsert(batch, dense_vecs, sparse_vecs)
        table_row_count += sum(1 for c in batch if c.type == "table_row")
        table_full_count += sum(1 for c in batch if c.type == "table_full")

    print(f"  📊 Table chunks indexed: {table_row_count} rows + {table_full_count} whole-table")

    total = text_total + table_row_count + table_full_count
    print(f"✅ Indexed {total} chunks total")

    return {"indexed_count": total, "status": "indexed"}


def extract_graph_artifacts(state: IngestionState) -> dict:
    if state.get("status") != "indexed":
        return {"status": state.get("status", "skipped")}

    version_id = state.get("version_id")
    doc_store = _get_doc_store()

    if settings.build_graph:
        meta = state["doc_meta"]
        docling_path = Path(state["docling_path"])

    # ── GRAPH branch (optional, BUILD_GRAPH=true) ────────────────────
        from rag.capabilities.extract import build_rule_chunks, process_chunk_graph
        from rag.storage.graph_store import Neo4jGraphStore

        graph_store = Neo4jGraphStore()
        embedder = get_embedder()
        sparse_embedder = get_sparse_embedder()
        all_rules = []
        prev_text = None
        graph_rule_count = 0

        text_chunks_for_graph = []
        chunker2 = HybridChunker(max_tokens=settings.max_chunk_tokens, merge_peers=True)
        doc2 = DoclingDocument.load_from_json(docling_path)
        for chunk in chunker2.chunk(doc2):
            page = _page_numbers(chunk.meta)
            text_chunks_for_graph.append({
                "text": chunk.text,
                "chunk_id": str(uuid.uuid4()),
                "page": page[0] if page else 0,
            })

        for i, ch in enumerate(text_chunks_for_graph):
            result = process_chunk_graph(
                chunk_text=ch["text"],
                chunk_id=ch["chunk_id"],
                doc_id=meta.doc_id,
                page=ch["page"],
                doc_version=meta.doc_version,
                graph_store=graph_store,
                prev_chunk_text=prev_text,
            )
            graph_rule_count += result["rules"]
            all_rules.extend(result["rule_artifacts"])
            prev_text = ch["text"]

            if (i + 1) % 10 == 0:
                print(f"  🔗 Graph: processed {i + 1}/{len(text_chunks_for_graph)} chunks")

        rule_chunks = build_rule_chunks(all_rules)
        if rule_chunks:
            rule_texts = [r.content for r in rule_chunks]
            rule_dense = [v.tolist() for v in embedder.embed(rule_texts, prefix=settings.dense_passage_prefix)]
            rule_sparse = [
                {"indices": sv.indices.tolist(), "values": sv.values.tolist()}
                for sv in sparse_embedder.embed(rule_texts)
            ]
            vec_store = _get_vec_store()
            vec_store.upsert(rule_chunks, rule_dense, rule_sparse)
        counts = graph_store.count()
        graph_store.close()
        print(f"  🔗 Graph: {counts['entities']} entities, {counts['relations']} relations")
        print(f"  📏 Rules: {graph_rule_count} extracted, {len(rule_chunks)} embedded")

    if version_id:
        doc_store.set_processing_state(version_id, ProcessingState.INDEXED)
        doc_store.activate_version(version_id)

    return {"status": "done"}


# ── Graph ────────────────────────────────────────────────────────────────

def build_ingestion_graph():
    g = StateGraph(IngestionState)
    g.add_node("convert", convert)
    g.add_node("chunk_and_index", chunk_and_index)
    g.add_node("extract_graph_artifacts", extract_graph_artifacts)
    g.add_edge(START, "convert")
    g.add_edge("convert", "chunk_and_index")
    g.add_edge("chunk_and_index", "extract_graph_artifacts")
    g.add_edge("extract_graph_artifacts", END)
    return g.compile()
