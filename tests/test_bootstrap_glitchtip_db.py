import subprocess
from unittest.mock import MagicMock, patch

import pytest

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


@patch("rag.bootstrap.glitchtip_db.time.sleep")
@patch("rag.bootstrap.glitchtip_db.subprocess.run")
def test_retries_the_whole_sequence_when_postgres_kills_the_connection_mid_statement(mock_run, mock_sleep):
    # Simulates the real race: a fresh Postgres container briefly accepts connections
    # during its own initdb bootstrap, then restarts for real, killing whatever was
    # mid-flight -- the first attempt's check fails, the second attempt succeeds.
    mock_run.side_effect = [
        subprocess.CalledProcessError(2, "psql"),  # first attempt: connection killed
        MagicMock(stdout=""),  # second attempt: check succeeds, not found
        MagicMock(),  # second attempt: CREATE DATABASE succeeds
    ]

    ensure_glitchtip_database()

    assert mock_run.call_count == 3
    assert mock_sleep.call_count == 1


@patch("rag.bootstrap.glitchtip_db.time.sleep")
@patch("rag.bootstrap.glitchtip_db.subprocess.run")
def test_raises_after_max_attempts_when_postgres_never_recovers(mock_run, mock_sleep):
    mock_run.side_effect = subprocess.CalledProcessError(2, "psql")

    with pytest.raises(subprocess.CalledProcessError):
        ensure_glitchtip_database(max_attempts=3, retry_delay=0.01)

    assert mock_run.call_count == 3
