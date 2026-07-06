import subprocess
from unittest.mock import MagicMock, patch

import pytest

from rag.bootstrap.wait_for_postgres import wait_for_postgres_ready


@patch("rag.bootstrap.wait_for_postgres.subprocess.run")
def test_returns_immediately_when_postgres_is_already_ready(mock_run):
    mock_run.return_value = MagicMock()

    wait_for_postgres_ready()

    mock_run.assert_called_once()


@patch("rag.bootstrap.wait_for_postgres.time.sleep")
@patch("rag.bootstrap.wait_for_postgres.subprocess.run")
def test_retries_until_postgres_becomes_ready(mock_run, mock_sleep):
    mock_run.side_effect = [
        subprocess.CalledProcessError(1, "pg_isready"),
        subprocess.CalledProcessError(1, "pg_isready"),
        MagicMock(),
    ]

    wait_for_postgres_ready(timeout_s=10.0, interval_s=0.01)

    assert mock_run.call_count == 3
    assert mock_sleep.call_count == 2


@patch("rag.bootstrap.wait_for_postgres.time.sleep")
@patch("rag.bootstrap.wait_for_postgres.subprocess.run")
def test_raises_after_timeout_when_postgres_never_becomes_ready(mock_run, mock_sleep):
    mock_run.side_effect = subprocess.CalledProcessError(1, "pg_isready")

    with pytest.raises(subprocess.CalledProcessError):
        wait_for_postgres_ready(timeout_s=0.0, interval_s=0.01)
