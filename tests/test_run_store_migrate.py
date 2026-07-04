"""Unit tests for run_store_migrate's per-store error-handling wrapper.

These test `_migrate_store` in isolation with mocks for the store factory and
`apply_pending` — this is a test of the error-handling behavior itself (one store
being unreachable or failing to migrate must not prevent reporting on/attempting the
other store), not a re-test of `apply_pending`'s own migration logic (covered in
tests/test_migrations_runner.py).
"""
from unittest.mock import MagicMock, patch

from run_store_migrate import _migrate_store


def test_migrate_store_returns_false_and_prints_message_when_store_unreachable(capsys):
    db = MagicMock()

    def failing_factory():
        raise ConnectionError("connection refused")

    with patch("run_store_migrate.apply_pending") as mock_apply_pending:
        result = _migrate_store(db, "neo4j", failing_factory, migrations=["irrelevant"])

    assert result is False
    mock_apply_pending.assert_not_called()
    out = capsys.readouterr().out
    assert "neo4j" in out
    assert "unreachable" in out
    assert "connection refused" in out


def test_migrate_store_returns_false_and_prints_message_when_apply_pending_raises(capsys):
    db = MagicMock()
    store = MagicMock()
    store_factory = MagicMock(return_value=store)

    with patch("run_store_migrate.apply_pending", side_effect=RuntimeError("migration boom")) as mock_apply_pending:
        result = _migrate_store(db, "qdrant", store_factory, migrations=["m1"])

    assert result is False
    mock_apply_pending.assert_called_once_with(db, store, "qdrant", ["m1"])
    out = capsys.readouterr().out
    assert "qdrant" in out
    assert "migration failed" in out
    assert "migration boom" in out


def test_migrate_store_returns_true_and_prints_applied_versions_on_success(capsys):
    db = MagicMock()
    store = MagicMock()
    store_factory = MagicMock(return_value=store)

    with patch("run_store_migrate.apply_pending", return_value=[1, 2]) as mock_apply_pending:
        result = _migrate_store(db, "qdrant", store_factory, migrations=["m1", "m2"])

    assert result is True
    mock_apply_pending.assert_called_once_with(db, store, "qdrant", ["m1", "m2"])
    out = capsys.readouterr().out
    assert "qdrant" in out
    assert "applied" in out
    assert "[1, 2]" in out


def test_migrate_store_returns_true_and_prints_up_to_date_when_nothing_applied(capsys):
    db = MagicMock()
    store = MagicMock()
    store_factory = MagicMock(return_value=store)

    with patch("run_store_migrate.apply_pending", return_value=[]) as mock_apply_pending:
        result = _migrate_store(db, "qdrant", store_factory, migrations=[])

    assert result is True
    mock_apply_pending.assert_called_once_with(db, store, "qdrant", [])
    out = capsys.readouterr().out
    assert "qdrant" in out
    assert "already up to date" in out


def test_main_attempts_neo4j_even_when_qdrant_construction_fails_and_exits_nonzero():
    """End-to-end sanity check on main(): both stores are always attempted, and a
    single failure causes a non-zero exit — without asserting real DB/store wiring."""
    import pytest

    with patch("run_store_migrate.SessionLocal") as mock_session_local, \
         patch("run_store_migrate.QdrantVectorStore", side_effect=RuntimeError("qdrant down")) as mock_qdrant, \
         patch("run_store_migrate.Neo4jGraphStore") as mock_neo4j, \
         patch("run_store_migrate.apply_pending", return_value=[1]):
        mock_session_local.return_value = MagicMock()

        from run_store_migrate import main

        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    mock_qdrant.assert_called_once()
    mock_neo4j.assert_called_once()  # neo4j is still attempted despite qdrant failing
