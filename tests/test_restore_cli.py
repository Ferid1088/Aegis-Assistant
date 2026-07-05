import shutil as _real_shutil
from pathlib import Path
from unittest.mock import MagicMock, call, patch

_real_copytree = _real_shutil.copytree


@patch("restore.subprocess.run")
@patch("restore.shutil.copy2")
@patch("restore.shutil.copytree")
@patch("restore.extract_tar")
@patch("restore.decrypt_archive")
@patch("restore.SessionLocal")
def test_run_restore_decrypts_extracts_and_restores_each_store(
    mock_session_local, mock_decrypt, mock_extract, mock_copytree, mock_copy2, mock_subprocess_run, tmp_path,
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
    assert mock_copy2.called
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

    # Pin the schema-reset call: it must exist, contain the DROP/CREATE commands,
    # and occur BEFORE the dump-replay psql call (which uses stdin=dump_file).
    # This regression-protects the fix added in commit 65addac that addresses
    # silent restore failure when the database already contains the schema.
    schema_reset_call_idx = None
    dump_replay_call_idx = None

    for idx, call_obj in enumerate(mock_subprocess_run.call_args_list):
        cmd = call_obj.args[0] if call_obj.args else []
        kwargs = call_obj.kwargs

        # Look for the schema-reset call: docker compose exec ... psql ... -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
        if (cmd and "psql" in cmd and "-c" in cmd):
            # Find the -c argument value
            try:
                c_idx = cmd.index("-c")
                if c_idx + 1 < len(cmd):
                    c_arg = cmd[c_idx + 1]
                    if "DROP SCHEMA public CASCADE" in c_arg and "CREATE SCHEMA public" in c_arg:
                        schema_reset_call_idx = idx
            except (ValueError, IndexError):
                pass

        # Look for the dump-replay call: has stdin=dump_file
        if "stdin" in kwargs and kwargs.get("stdin") is not None:
            dump_replay_call_idx = idx

    assert schema_reset_call_idx is not None, "schema-reset call with 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' not found"
    assert dump_replay_call_idx is not None, "dump-replay call with stdin=dump_file not found"
    assert schema_reset_call_idx < dump_replay_call_idx, "schema-reset call must occur before dump-replay call"
