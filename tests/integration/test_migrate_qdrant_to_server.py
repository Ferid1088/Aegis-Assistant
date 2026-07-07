"""Requires a running Docker daemon: populates a real embedded-mode Qdrant
collection, brings up the real `qdrant` service, runs the migration tool
against it, and confirms every point is present and queryable in the
server-mode collection afterward.

Run with: uv run pytest tests/integration/test_migrate_qdrant_to_server.py -v -s
"""
import subprocess
import time

import httpx
import pytest


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_migration_copies_all_points_to_server(monkeypatch, tmp_path):
    from rag.config import settings
    from rag.models import ChunkRecord
    from rag.storage.vector_store import QdrantVectorStore

    embedded_path = str(tmp_path / "qdrant-embedded")
    collection = "test_migration_8_10a"
    monkeypatch.setattr(settings, "qdrant_path", embedded_path)
    monkeypatch.setattr(settings, "qdrant_collection", collection)
    monkeypatch.setattr(settings, "qdrant_url", "")

    embedded_store = QdrantVectorStore()
    embedded_store.ensure_collection(dense_dim=4)
    chunks = [
        ChunkRecord(
            chunk_id=f"11111111-1111-1111-1111-11111111111{i}", type="text",
            content=f"migration test chunk {i}", source_file="x.pdf", doc_id="d1",
            page_numbers=[1], heading_path=[], bboxes=[],
        )
        for i in range(3)
    ]
    embedded_store.upsert(
        chunks,
        dense=[[0.1, 0.2, 0.3, 0.4]] * 3,
        sparse=[{"indices": [1], "values": [1.0]}] * 3,
    )
    embedded_store.client.close()

    subprocess.run(["docker", "compose", "up", "-d", "qdrant"], check=True)
    for _ in range(30):
        try:
            r = httpx.get("http://localhost:6333/collections", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        pytest.fail("qdrant server did not become reachable on 127.0.0.1:6333")

    from migrate_qdrant_to_server import migrate
    migrated_count = migrate(server_url="http://localhost:6333", batch_size=2)
    assert migrated_count == 3

    from qdrant_client import QdrantClient
    server_client = QdrantClient(url="http://localhost:6333")
    assert server_client.count(collection).count == 3
    points, _ = server_client.scroll(collection_name=collection, limit=10, with_payload=True)
    contents = {p.payload["content"] for p in points}
    assert contents == {f"migration test chunk {i}" for i in range(3)}

    server_client.delete_collection(collection)
