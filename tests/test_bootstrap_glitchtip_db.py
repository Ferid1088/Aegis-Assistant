from unittest.mock import MagicMock, patch

from rag.bootstrap.glitchtip_db import ensure_glitchtip_database


@patch("rag.bootstrap.glitchtip_db.subprocess.run")
def test_creates_the_database_when_missing(mock_run):
    mock_run.side_effect = [
        MagicMock(stdout=""),  # SELECT 1 FROM pg_database ... -> not found
        MagicMock(),  # CREATE DATABASE succeeds
    ]

    ensure_glitchtip_database()

    assert mock_run.call_count == 2
    create_call_args = mock_run.call_args_list[1].args[0]
    assert "CREATE DATABASE glitchtip" in " ".join(create_call_args)


@patch("rag.bootstrap.glitchtip_db.subprocess.run")
def test_skips_creation_when_database_already_exists(mock_run):
    mock_run.return_value = MagicMock(stdout="1\n")

    ensure_glitchtip_database()

    assert mock_run.call_count == 1  # only the existence check, no CREATE DATABASE
