"""Test that logical_doc_id round-trips through Qdrant payload.

Tests 02.1 fix: logical_doc_id is now included in the payload dict when upserting,
so it can be retrieved from stored points.
"""

import shutil
import tempfile
import uuid

from rag.config import settings
from rag.models import ChunkRecord
from rag.storage.vector_store import QdrantVectorStore


def test_logical_doc_id_round_trips_through_qdrant_payload():
    """Verify logical_doc_id is stored in Qdrant payload and can be retrieved."""
    # Save original settings
    original_qdrant_path = settings.qdrant_path
    original_qdrant_collection = settings.qdrant_collection

    # Create a temporary directory for this test
    tmpdir = tempfile.mkdtemp()

    try:
        # Override settings to use a temporary path and unique collection name
        settings.qdrant_path = tmpdir
        settings.qdrant_collection = "test_logical_doc_id"

        # Create store with temporary settings
        store = QdrantVectorStore()

        # Create a minimal ChunkRecord with logical_doc_id set
        chunk_id_value = str(uuid.uuid4())
        chunk = ChunkRecord(
            chunk_id=chunk_id_value,
            type="text",
            content="Test content with logical doc ID",
            source_file="test.pdf",
            doc_id="doc_v1",
            doc_version="1.0",
            page_numbers=[1],
            heading_path=[],
            bboxes=[],
            logical_doc_id="LOGICAL-TEST-1",  # This should be stored in the payload
        )

        # Create a 4-dimensional dense vector
        dense_vector = [0.1, 0.2, 0.3, 0.4]

        # Create a trivial sparse vector
        sparse_vector = {"indices": [0], "values": [1.0]}

        # Ensure collection exists with dense_dim=4
        store.ensure_collection(dense_dim=4)

        # Upsert the chunk
        store.upsert([chunk], [dense_vector], [sparse_vector])

        # Retrieve the point directly from the underlying Qdrant client
        retrieved_points = store.client.retrieve(
            collection_name=store.collection,
            ids=[chunk_id_value],
            with_payload=True,
        )

        # Verify the payload contains logical_doc_id
        assert len(retrieved_points) == 1, "Expected exactly one retrieved point"
        payload = retrieved_points[0].payload
        assert payload is not None, "Payload should not be None"
        assert "logical_doc_id" in payload, "Payload should contain logical_doc_id key"
        assert (
            payload["logical_doc_id"] == "LOGICAL-TEST-1"
        ), f"logical_doc_id should be 'LOGICAL-TEST-1', got {payload['logical_doc_id']}"

    finally:
        # Restore original settings
        settings.qdrant_path = original_qdrant_path
        settings.qdrant_collection = original_qdrant_collection

        # Clean up temp directory
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_chunk_record_has_is_current_field():
    from rag.models import ChunkRecord
    rec = ChunkRecord(
        chunk_id="abc",
        type="text",
        content="hello",
        source_file="file.pdf",
        doc_id="d1",
        page_numbers=[1],
        heading_path=[],
        bboxes=[],
    )
    assert rec.is_current is True


def test_upsert_includes_is_current(tmp_path):
    from unittest.mock import MagicMock, patch
    from rag.models import ChunkRecord
    from rag.storage.vector_store import QdrantVectorStore

    rec = ChunkRecord(
        chunk_id="c1",
        type="text",
        content="hello",
        source_file="f.pdf",
        doc_id="d1",
        page_numbers=[1],
        heading_path=[],
        bboxes=[],
        is_current=False,
    )

    with patch("rag.storage.vector_store.QdrantClient") as MockClient:
        instance = MockClient.return_value
        vs = QdrantVectorStore.__new__(QdrantVectorStore)
        vs.client = instance
        vs.collection = "documents"

        vs.upsert([rec], [[0.1, 0.2]], [{"indices": [0], "values": [1.0]}])

        call_args = instance.upsert.call_args
        point = call_args[0][1][0]
        assert point.payload["is_current"] is False
