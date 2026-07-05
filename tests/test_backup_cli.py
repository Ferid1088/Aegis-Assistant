from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


@patch("backup.prune_old_backups")
@patch("backup.encrypt_archive")
@patch("backup.build_tar")
@patch("backup.copy_audit_log")
@patch("backup.backup_sqlite_file")
@patch("backup.dump_neo4j")
@patch("backup.copy_qdrant")
@patch("backup.dump_postgres")
@patch("backup.SessionLocal")
def test_run_backup_calls_all_capture_steps_then_encrypts_and_prunes(
    mock_session_local, mock_dump_pg, mock_copy_qdrant, mock_dump_neo4j,
    mock_backup_sqlite, mock_copy_audit, mock_build_tar, mock_encrypt, mock_prune,
    tmp_path,
):
    mock_session_local.return_value = MagicMock()
    mock_build_tar.return_value = tmp_path / "plain.tar"

    import backup
    backup.run_backup(backup_dir=tmp_path)

    mock_dump_pg.assert_called_once()
    mock_copy_qdrant.assert_called_once()
    mock_dump_neo4j.assert_called_once()
    assert mock_backup_sqlite.call_count == 2  # documents.db + observability.db
    mock_copy_audit.assert_called_once()
    mock_build_tar.assert_called_once()
    mock_encrypt.assert_called_once()
    mock_prune.assert_called_once()


@patch("backup.build_tar")
@patch("backup.copy_audit_log")
@patch("backup.backup_sqlite_file")
@patch("backup.dump_neo4j")
@patch("backup.copy_qdrant")
@patch("backup.dump_postgres")
@patch("backup.SessionLocal")
def test_run_backup_aborts_before_encrypting_if_a_capture_step_fails(
    mock_session_local, mock_dump_pg, mock_copy_qdrant, mock_dump_neo4j,
    mock_backup_sqlite, mock_copy_audit, mock_build_tar, tmp_path,
):
    mock_session_local.return_value = MagicMock()
    mock_dump_neo4j.side_effect = RuntimeError("neo4j copy failed")

    import backup
    import pytest
    with pytest.raises(RuntimeError):
        backup.run_backup(backup_dir=tmp_path)

    mock_build_tar.assert_not_called()
    assert list(tmp_path.glob("appliance-backup-*.tar.enc")) == []
