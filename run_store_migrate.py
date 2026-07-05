"""CLI entry point for applying pending Qdrant/Neo4j schema migrations."""

import sys
import time

from rag.migrations.neo4j.migration_0001_baseline import MIGRATION as NEO4J_0001
from rag.migrations.qdrant.migration_0001_baseline import MIGRATION as QDRANT_0001
from rag.migrations.runner import apply_pending
from rag.storage.graph_store import Neo4jGraphStore
from rag.storage.sql.base import SessionLocal
from rag.storage.vector_store import QdrantVectorStore

QDRANT_MIGRATIONS = [QDRANT_0001]
NEO4J_MIGRATIONS = [NEO4J_0001]


def _migrate_store(
    db, store_name: str, store_factory, migrations, max_attempts: int = 10, retry_delay: float = 2.0,
) -> bool:
    """Construct `store_name` via `store_factory` and apply its pending migrations.

    Returns True on success, False on failure (constructing the store or applying its
    migrations) — printing a clear, operator-readable message in either case rather
    than letting the exception propagate. This keeps one store's outage (e.g. Neo4j
    down during an update) from crashing the process before the other store is even
    attempted.

    Retries construction up to `max_attempts` times, `retry_delay` seconds apart, so a
    store that's still cold-starting (e.g. Neo4j's Bolt port not yet accepting
    connections moments after `docker compose up -d` creates the container) doesn't
    abort the very first install run.
    """
    store = None
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            store = store_factory()
            break
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(retry_delay)

    if store is None:
        print(f"{store_name}: unreachable after {max_attempts} attempts — {last_exc}")
        return False

    try:
        applied = apply_pending(db, store, store_name, migrations)
        print(f"{store_name}: applied {applied}" if applied else f"{store_name}: already up to date")
        return True
    except Exception as exc:
        print(f"{store_name}: migration failed — {exc}")
        return False


def main():
    db = SessionLocal()
    try:
        qdrant_ok = _migrate_store(db, "qdrant", QdrantVectorStore, QDRANT_MIGRATIONS)
        neo4j_ok = _migrate_store(db, "neo4j", Neo4jGraphStore, NEO4J_MIGRATIONS)
    finally:
        db.close()

    if not (qdrant_ok and neo4j_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
