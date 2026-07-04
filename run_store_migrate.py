"""CLI entry point for applying pending Qdrant/Neo4j schema migrations."""

from rag.migrations.neo4j.migration_0001_baseline import MIGRATION as NEO4J_0001
from rag.migrations.qdrant.migration_0001_baseline import MIGRATION as QDRANT_0001
from rag.migrations.runner import apply_pending
from rag.storage.graph_store import Neo4jGraphStore
from rag.storage.sql.base import SessionLocal
from rag.storage.vector_store import QdrantVectorStore

QDRANT_MIGRATIONS = [QDRANT_0001]
NEO4J_MIGRATIONS = [NEO4J_0001]


def main():
    db = SessionLocal()
    try:
        applied = apply_pending(db, QdrantVectorStore(), "qdrant", QDRANT_MIGRATIONS)
        print(f"qdrant: applied {applied}" if applied else "qdrant: already up to date")

        applied = apply_pending(db, Neo4jGraphStore(), "neo4j", NEO4J_MIGRATIONS)
        print(f"neo4j: applied {applied}" if applied else "neo4j: already up to date")
    finally:
        db.close()


if __name__ == "__main__":
    main()
