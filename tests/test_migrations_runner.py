from typing import Protocol
from unittest.mock import MagicMock

from rag.migrations.base import Migration


def test_migration_protocol_shape():
    class FakeMigration:
        version = 1
        def apply(self, store: object) -> None:
            pass

    m: Migration = FakeMigration()
    assert m.version == 1
    assert isinstance(Migration, type(Protocol))


def test_qdrant_baseline_migration_calls_ensure_collection():
    from rag.migrations.qdrant.migration_0001_baseline import MIGRATION

    assert MIGRATION.version == 1
    fake_store = MagicMock()
    MIGRATION.apply(fake_store)
    fake_store.ensure_collection.assert_called_once_with(dense_dim=1024)


def test_neo4j_baseline_migration_calls_ensure_indexes():
    from rag.migrations.neo4j.migration_0001_baseline import MIGRATION

    assert MIGRATION.version == 1
    fake_store = MagicMock()
    MIGRATION.apply(fake_store)
    fake_store._ensure_indexes.assert_called_once_with()
