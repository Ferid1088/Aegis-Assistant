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
def test_copy_qdrant_copies_configured_path(mock_settings, mock_copytree, tmp_path):
    mock_settings.qdrant_path = "/fake/qdrant/path"
    dest = tmp_path / "qdrant_copy"

    copy_qdrant(dest)

    mock_copytree.assert_called_once_with(Path("/fake/qdrant/path"), dest, dirs_exist_ok=True)


@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.subprocess.run")
def test_dump_neo4j_stops_copies_then_restarts(mock_run, mock_copytree, tmp_path):
    dest = tmp_path / "neo4j_copy"

    dump_neo4j(dest)

    assert mock_run.call_args_list == [
        call(["docker", "compose", "stop", "neo4j"], check=True),
        call(["docker", "compose", "start", "neo4j"], check=True),
    ]
    mock_copytree.assert_called_once()


@patch("rag.backup.capture.shutil.copytree")
@patch("rag.backup.capture.subprocess.run")
def test_dump_neo4j_restarts_even_if_copy_fails(mock_run, mock_copytree, tmp_path):
    mock_copytree.side_effect = OSError("disk full")
    dest = tmp_path / "neo4j_copy"

    try:
        dump_neo4j(dest)
    except OSError:
        pass

    assert call(["docker", "compose", "start", "neo4j"], check=True) in mock_run.call_args_list


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
def test_copy_audit_log_copies_configured_dir(mock_settings, mock_copytree, tmp_path):
    mock_settings.audit_log_dir = "data/audit"
    dest = tmp_path / "audit_copy"

    copy_audit_log(dest)

    mock_copytree.assert_called_once_with(Path("data/audit"), dest, dirs_exist_ok=True)
