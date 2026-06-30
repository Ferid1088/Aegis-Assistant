from rag.models import ChunkRecord, DocumentMeta


def test_chunk_record_logical_doc_id_defaults_to_none():
    chunk = ChunkRecord(
        chunk_id="c1", type="text", content="hello", source_file="f.pdf",
        doc_id="d1", page_numbers=[1], heading_path=[], bboxes=[],
    )
    assert chunk.logical_doc_id is None


def test_chunk_record_logical_doc_id_settable():
    chunk = ChunkRecord(
        chunk_id="c1", type="text", content="hello", source_file="f.pdf",
        doc_id="d1", page_numbers=[1], heading_path=[], bboxes=[],
        logical_doc_id="L1",
    )
    assert chunk.logical_doc_id == "L1"


def test_document_meta_logical_doc_id_defaults_to_none():
    meta = DocumentMeta(doc_id="d1", filename="f.pdf", content_hash="h1", num_pages=1)
    assert meta.logical_doc_id is None


def test_document_meta_logical_doc_id_settable():
    meta = DocumentMeta(
        doc_id="d1", filename="f.pdf", content_hash="h1", num_pages=1,
        logical_doc_id="L1",
    )
    assert meta.logical_doc_id == "L1"
