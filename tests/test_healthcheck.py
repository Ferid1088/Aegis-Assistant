from unittest.mock import MagicMock, patch

import pytest

from rag.healthcheck import check_postgres


@patch("rag.healthcheck.SessionLocal")
def test_check_postgres_passes_when_query_succeeds(mock_session_local):
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    check_postgres()  # must not raise

    mock_db.execute.assert_called_once()
    mock_db.close.assert_called_once()


@patch("rag.healthcheck.SessionLocal")
def test_check_postgres_raises_when_query_fails(mock_session_local):
    mock_db = MagicMock()
    mock_db.execute.side_effect = RuntimeError("connection refused")
    mock_session_local.return_value = mock_db

    with pytest.raises(RuntimeError):
        check_postgres()

    mock_db.close.assert_called_once()
