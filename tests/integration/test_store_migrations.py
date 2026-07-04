"""Requires a running Postgres: `docker compose up -d postgres` before running.
Embedded Qdrant needs no separate service (just a writable tmp_path). The Neo4j test
is skipped automatically if a local Neo4j is not reachable.

Run with: uv run pytest tests/integration/test_store_migrations.py -v -s
"""
import shutil

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from rag.config import settings
from rag.migrations.qdrant.migration_0001_baseline import MIGRATION as QDRANT_0001
from rag.migrations.runner import apply_pending, get_current_version
from rag.storage.sql import models  # noqa: F401  (registers models on Base.metadata)
from rag.storage.sql.base import Base
from rag.storage.vector_store import QdrantVectorStore


@pytest.fixture()
def pg_session():
    """Mirrors tests/integration/test_local_auth_flow.py's real-Postgres fixture pattern:
    a fresh engine against settings.database_url, tables dropped/created per test.

    `store_schema_versions` deliberately has no ORM model (it's raw-SQL,
    migration-runner-internal bookkeeping — see Task 1), so it is absent from
    `Base.metadata` and `Base.metadata.create_all` never creates it. Normally it exists
    already via the Alembic migration in alembic/versions/0004_store_schema_versions.py,
    but a genuinely fresh `docker compose up -d postgres` volume won't have that applied.
    Create it here with `IF NOT EXISTS` (mirroring that migration's column shape) so this
    fixture is self-sufficient regardless of migration state, without disturbing an
    already-migrated database.
    """
    engine = create_engine(settings.database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS store_schema_versions (
                store_name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    session.commit()

    yield session

    session.execute(text("DELETE FROM store_schema_versions"))
    session.commit()
    session.close()
    engine.dispose()


def test_qdrant_baseline_migration_applies_for_real(pg_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "qdrant_path", str(tmp_path / "qdrant"))
    store = QdrantVectorStore()

    applied = apply_pending(pg_session, store, "qdrant", [QDRANT_0001])
    assert applied == [1]
    assert get_current_version(pg_session, "qdrant") == 1
    assert store.client.collection_exists(store.collection)

    applied_again = apply_pending(pg_session, store, "qdrant", [QDRANT_0001])
    assert applied_again == []
    assert get_current_version(pg_session, "qdrant") == 1

    store.client.close()
    shutil.rmtree(tmp_path / "qdrant", ignore_errors=True)


def _neo4j_reachable() -> bool:
    try:
        from rag.storage.graph_store import Neo4jGraphStore
        store = Neo4jGraphStore()
        store.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _neo4j_reachable(), reason="Neo4j not reachable locally")
def test_neo4j_baseline_migration_applies_for_real(pg_session):
    from rag.migrations.neo4j.migration_0001_baseline import MIGRATION as NEO4J_0001
    from rag.storage.graph_store import Neo4jGraphStore

    store = Neo4jGraphStore()
    try:
        applied = apply_pending(pg_session, store, "neo4j", [NEO4J_0001])
        assert applied == [1]
        assert get_current_version(pg_session, "neo4j") == 1

        applied_again = apply_pending(pg_session, store, "neo4j", [NEO4J_0001])
        assert applied_again == []
    finally:
        store.close()
