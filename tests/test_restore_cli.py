import shutil as _real_shutil
from pathlib import Path
from unittest.mock import MagicMock, call, patch

_real_copytree = _real_shutil.copytree


@patch("restore.subprocess.run")
@patch("restore.shutil.copytree")
@patch("restore.extract_tar")
@patch("restore.decrypt_archive")
@patch("restore.SessionLocal")
def test_run_restore_decrypts_extracts_and_restores_each_store(
    mock_session_local, mock_decrypt, mock_extract, mock_copytree, mock_subprocess_run, tmp_path,
):
    mock_session_local.return_value = MagicMock()

    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    (extracted_dir / "postgres.dump").write_bytes(b"-- fake dump")
    (extracted_dir / "qdrant").mkdir()
    (extracted_dir / "neo4j").mkdir()
    (extracted_dir / "documents.db").write_bytes(b"fake db")
    (extracted_dir / "observability.db").write_bytes(b"fake db")
    (extracted_dir / "audit").mkdir()

    def fake_extract(tar_path, dest_dir):
        _real_copytree(extracted_dir, dest_dir, dirs_exist_ok=True)
    mock_extract.side_effect = fake_extract
    mock_decrypt.return_value = tmp_path / "decrypted.tar"
    (tmp_path / "decrypted.tar").write_bytes(b"fake tar")

    import restore
    restore.run_restore(Path("some-backup.tar.enc"))

    mock_decrypt.assert_called_once()
    mock_extract.assert_called_once()
    assert any(
        c == call(["docker", "compose", "stop", "neo4j"], check=True)
        for c in mock_subprocess_run.call_args_list
    )
    assert any(
        c == call(["docker", "compose", "start", "neo4j"], check=True)
        for c in mock_subprocess_run.call_args_list
    )
    assert any(
        "psql" in c.args[0] for c in mock_subprocess_run.call_args_list if c.args
    )
