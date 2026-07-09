from typing import Protocol
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from rag.migrations.base import Migration
from rag.migrations.runner import apply_pending, get_current_version


@pytest.fixture(autouse=True)
def _store_schema_versions_table(db_session):
    """The `db_session` fixture (tests/conftest.py) only creates tables registered on
    `Base.metadata`. `store_schema_versions` deliberately has no ORM model (it's raw-SQL,
    migration-runner-internal bookkeeping — see Task 1), so it's absent from the ORM's
    metadata and never gets created there. Against real Postgres this table always
    exists already (applied once via the Alembic migration in
    alembic/versions/0004_store_schema_versions.py); this fixture recreates that same
    shape directly against the in-memory SQLite engine so this test module can use the
    shared `db_session` fixture as the brief specifies.
    """
    db_session.execute(
        text(
            """
            CREATE TABLE store_schema_versions (
                store_name VARCHAR PRIMARY KEY,
                version INTEGER NOT NULL,
                applied_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
            """
        )
    )
    db_session.commit()


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


def test_get_current_version_returns_zero_when_untracked(db_session):
    assert get_current_version(db_session, "nonexistent_store") == 0


class _FakeMigration:
    def __init__(self, version, calls, fail=False):
        self.version = version
        self._calls = calls
        self._fail = fail

    def apply(self, store):
        self._calls.append(self.version)
        if self._fail:
            raise RuntimeError(f"migration {self.version} failed")


def test_apply_pending_applies_all_migrations_in_order_and_records_version(db_session):
    calls = []
    migrations = [_FakeMigration(1, calls), _FakeMigration(2, calls), _FakeMigration(3, calls)]

    applied = apply_pending(db_session, store=object(), store_name="widget", migrations=migrations)

    assert applied == [1, 2, 3]
    assert calls == [1, 2, 3]
    assert get_current_version(db_session, "widget") == 3


def test_apply_pending_is_idempotent_second_run_applies_nothing(db_session):
    calls = []
    migrations = [_FakeMigration(1, calls)]

    apply_pending(db_session, store=object(), store_name="widget", migrations=migrations)
    applied_again = apply_pending(db_session, store=object(), store_name="widget", migrations=migrations)

    assert applied_again == []
    assert calls == [1]


def test_apply_pending_only_applies_migrations_above_current_version(db_session):
    calls = []
    migrations = [_FakeMigration(1, calls), _FakeMigration(2, calls)]
    apply_pending(db_session, store=object(), store_name="widget", migrations=migrations)

    calls.clear()
    migrations_v3 = [_FakeMigration(1, calls), _FakeMigration(2, calls), _FakeMigration(3, calls)]
    applied = apply_pending(db_session, store=object(), store_name="widget", migrations=migrations_v3)

    assert applied == [3]
    assert calls == [3]


def test_apply_pending_stops_at_first_failure_and_keeps_last_successful_version(db_session):
    calls = []
    migrations = [_FakeMigration(1, calls), _FakeMigration(2, calls, fail=True), _FakeMigration(3, calls)]

    with pytest.raises(RuntimeError, match="migration 2 failed"):
        apply_pending(db_session, store=object(), store_name="widget", migrations=migrations)

    assert calls == [1, 2]
    assert get_current_version(db_session, "widget") == 1
