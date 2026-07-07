from pathlib import Path
from unittest.mock import call, patch

from rag.backup.capture import (
    backup_sqlite_file, copy_audit_log, copy_qdrant, dump_neo4j, dump_postgres,
)


@patch("rag.backup.capture.subprocess.run")
def test_dump_postgres_runs_pg_dump_and_writes_stdout(mock_run, tmp_path):
    mock_run.return_value.stdout = b"-- fake pg dump content"
    dest = tmp_path / "postgres.dump"

    dump_postgres(dest)

    mock_run.assert_called_once_with(
        ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "postgres", "appliance"],
        capture_output=True, check=True,
    )
    assert dest.read_bytes() == b"-- fake pg dump content"


@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.settings")
def test_copy_qdrant_copies_configured_path_in_embedded_mode(mock_settings, mock_copytree, tmp_path):
    # Embedded mode (qdrant_url empty): no separate server process holds
    # data/qdrant open, so this must stay a plain copytree -- no docker compose
    # stop/start.
    mock_settings.qdrant_path = "/fake/qdrant/path"
    mock_settings.qdrant_url = ""
    dest = tmp_path / "qdrant_copy"

    with patch("rag.backup.capture.subprocess.run") as mock_run:
        copy_qdrant(dest)
        mock_run.assert_not_called()

    mock_copytree.assert_called_once_with(Path("/fake/qdrant/path"), dest, dirs_exist_ok=True)


@patch("rag.backup.capture.wait_for_qdrant_ready")
@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.subprocess.run")
@patch("rag.backup.capture.settings")
def test_copy_qdrant_stops_copies_then_restarts_in_server_mode(
    mock_settings, mock_run, mock_copytree, mock_wait_ready, tmp_path,
):
    mock_settings.qdrant_path = "/fake/qdrant/path"
    mock_settings.qdrant_url = "http://localhost:6333"
    dest = tmp_path / "qdrant_copy"

    copy_qdrant(dest)

    assert mock_run.call_args_list == [
        call(["docker", "compose", "stop", "qdrant"], check=True),
        call(["docker", "compose", "start", "qdrant"], check=True),
    ]
    mock_copytree.assert_called_once_with(Path("/fake/qdrant/path"), dest, dirs_exist_ok=True)
    mock_wait_ready.assert_called_once()


@patch("rag.backup.capture.wait_for_qdrant_ready")
@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.subprocess.run")
@patch("rag.backup.capture.settings")
def test_copy_qdrant_restarts_even_if_copy_fails_in_server_mode(
    mock_settings, mock_run, mock_copytree, mock_wait_ready, tmp_path,
):
    mock_settings.qdrant_path = "/fake/qdrant/path"
    mock_settings.qdrant_url = "http://localhost:6333"
    mock_copytree.side_effect = OSError("disk full")
    dest = tmp_path / "qdrant_copy"

    try:
        copy_qdrant(dest)
    except OSError:
        pass

    assert call(["docker", "compose", "start", "qdrant"], check=True) in mock_run.call_args_list
    mock_wait_ready.assert_called_once()


@patch("rag.backup.capture.wait_for_neo4j_ready")
@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.subprocess.run")
def test_dump_neo4j_stops_copies_then_restarts(mock_run, mock_copytree, mock_wait_ready, tmp_path):
    dest = tmp_path / "neo4j_copy"

    dump_neo4j(dest)

    assert mock_run.call_args_list == [
        call(["docker", "compose", "stop", "neo4j"], check=True),
        call(["docker", "compose", "start", "neo4j"], check=True),
    ]
    mock_copytree.assert_called_once()
    mock_wait_ready.assert_called_once()


@patch("rag.backup.capture.wait_for_neo4j_ready")
@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.subprocess.run")
def test_dump_neo4j_restarts_even_if_copy_fails(mock_run, mock_copytree, mock_wait_ready, tmp_path):
    mock_copytree.side_effect = OSError("disk full")
    dest = tmp_path / "neo4j_copy"

    try:
        dump_neo4j(dest)
    except OSError:
        pass

    assert call(["docker", "compose", "start", "neo4j"], check=True) in mock_run.call_args_list
    mock_wait_ready.assert_called_once()


@patch("rag.backup.capture.subprocess.run")
def test_backup_sqlite_file_runs_sqlite3_backup_command(mock_run, tmp_path):
    src = tmp_path / "documents.db"
    dest = tmp_path / "documents_copy.db"

    backup_sqlite_file(src, dest)

    mock_run.assert_called_once_with(
        ["sqlite3", str(src), f".backup {dest}"], check=True,
    )


@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.settings")
def test_copy_audit_log_copies_configured_dir_when_it_exists(mock_settings, mock_copytree, tmp_path):
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    mock_settings.audit_log_dir = str(audit_dir)
    dest = tmp_path / "audit_copy"

    copy_audit_log(dest)

    mock_copytree.assert_called_once_with(audit_dir, dest, dirs_exist_ok=True)


@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.settings")
def test_copy_audit_log_writes_empty_dir_when_source_never_existed(mock_settings, mock_copytree, tmp_path):
    # A fresh appliance backed up before its first audit-worthy event has no
    # data/audit directory yet (see AuditLog.__init__) -- copy_audit_log must not
    # error in that case, just leave an empty destination.
    mock_settings.audit_log_dir = str(tmp_path / "audit-never-created")
    dest = tmp_path / "audit_copy"

    copy_audit_log(dest)

    mock_copytree.assert_not_called()
    assert dest.is_dir()
