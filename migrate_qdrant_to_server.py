"""One-time migration: copies every point from an embedded-mode Qdrant
collection into a running server-mode Qdrant collection.

Phase 8.10a found that embedded mode's on-disk format (a separate
pure-Python/SQLite reimplementation bundled in qdrant-client) is NOT
compatible with the real server's on-disk format (raft + segment
storage) -- pointing a server container at embedded-written files
silently starts empty rather than erroring. The client-facing API IS
confirmed compatible across both modes, so this migrates data at that
level: scroll every point out of the embedded collection, re-upsert it
into the server-mode collection.

Usage:
    uv run python migrate_qdrant_to_server.py --server-url http://localhost:6333
"""
import argparse

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from rag.config import settings
from rag.storage.vector_store import QdrantVectorStore


def migrate(server_url: str, batch_size: int = 100) -> int:
    embedded_client = QdrantClient(path=settings.qdrant_path)
    collection = settings.qdrant_collection

    if not embedded_client.collection_exists(collection):
        print(f"No embedded collection '{collection}' found at {settings.qdrant_path} -- nothing to migrate.")
        return 0

    # Derive dense_dim from the embedded collection's own stored config,
    # not from a fresh call to get_embedder(): the embedder is a mutable,
    # config-driven singleton (settings.dense_embedding_model) that need not
    # match whatever model actually produced the vectors already sitting in
    # the embedded collection. Confirmed for real that trusting the live
    # embedder instead is actively wrong -- it raised a 400 "Vector dimension
    # error: expected dim: 1024, got 4 for vector 'dense'" against a real
    # server when the embedded collection's real stored dimension (4, in that
    # repro) didn't match the live embedder's output dimension (1024).
    dense_dim = embedded_client.get_collection(collection).config.params.vectors["dense"].size

    settings.qdrant_url = server_url
    server_store = QdrantVectorStore()
    server_store.ensure_collection(dense_dim=dense_dim)

    migrated = 0
    offset = None
    while True:
        points, offset = embedded_client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            break
        # embedded_client.scroll() returns qdrant_client.http.models.Record
        # objects (id/payload/vector/shard_key/order_value) -- verified
        # against the actual installed qdrant-client==1.18.0 -- which
        # .upsert() rejects outright (it requires PointStruct instances or
        # plain dicts, not Record). Confirmed for real: passing scroll's
        # Record objects straight through raised a pydantic ValidationError
        # ("Input should be a valid dictionary or instance of PointStruct").
        # Re-wrap each Record's id/vector/payload into a PointStruct before
        # upserting.
        point_structs = [
            qm.PointStruct(id=record.id, vector=record.vector, payload=record.payload)
            for record in points
        ]
        server_store.client.upsert(collection_name=collection, points=point_structs)
        migrated += len(points)
        if offset is None:
            break

    return migrated


def main():
    parser = argparse.ArgumentParser(
        description="Migrate an embedded-mode Qdrant collection to a running server"
    )
    parser.add_argument(
        "--server-url", default="http://localhost:6333",
        help="URL of the already-running Qdrant server to migrate into",
    )
    args = parser.parse_args()

    count = migrate(args.server_url)
    print(
        f"Migrated {count} point(s) from embedded ({settings.qdrant_path}) "
        f"to server ({args.server_url})."
    )


if __name__ == "__main__":
    main()
