from unittest.mock import MagicMock, patch

import pytest

from rag.healthcheck import check_postgres, check_redis


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


@patch("rag.healthcheck.get_redis")
def test_check_redis_passes_when_client_available(mock_get_redis):
    mock_client = MagicMock()
    mock_get_redis.return_value = mock_client

    check_redis()  # must not raise

    mock_client.ping.assert_called_once()


@patch("rag.healthcheck.get_redis")
def test_check_redis_raises_when_client_unavailable(mock_get_redis):
    mock_get_redis.return_value = None

    with pytest.raises(RuntimeError):
        check_redis()


@patch("rag.healthcheck.get_redis")
def test_check_redis_raises_when_cached_client_is_actually_dead(mock_get_redis):
    # get_redis() caches its client forever once connected once (see
    # rag/capabilities/cache.py) -- it does NOT re-verify liveness on later
    # calls. check_redis() must re-validate with a live ping() every time it
    # is called, or a Redis outage that happens AFTER the first successful
    # connection would never be detected (Phase 8.10b).
    dead_client = MagicMock()
    dead_client.ping.side_effect = ConnectionError("Connection refused")
    mock_get_redis.return_value = dead_client

    with pytest.raises(ConnectionError):
        check_redis()
