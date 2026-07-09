from unittest.mock import MagicMock, patch

import pytest

from rag.bootstrap.wait_for_neo4j import wait_for_neo4j_ready


@patch("rag.infra.stores.graph_store.Neo4jGraphStore")
def test_returns_immediately_when_neo4j_is_already_ready(mock_store_cls):
    mock_store_cls.return_value = MagicMock()

    wait_for_neo4j_ready()

    mock_store_cls.assert_called_once()


@patch("rag.bootstrap.wait_for_neo4j.time.sleep")
@patch("rag.infra.stores.graph_store.Neo4jGraphStore")
def test_retries_until_neo4j_becomes_ready(mock_store_cls, mock_sleep):
    mock_store_cls.side_effect = [
        ConnectionError("connection refused"),
        ConnectionError("connection refused"),
        MagicMock(),
    ]

    wait_for_neo4j_ready(timeout_s=10.0, interval_s=0.01)

    assert mock_store_cls.call_count == 3
    assert mock_sleep.call_count == 2


@patch("rag.bootstrap.wait_for_neo4j.time.monotonic")
@patch("rag.infra.stores.graph_store.Neo4jGraphStore")
def test_raises_after_timeout_when_neo4j_never_becomes_ready(mock_store_cls, mock_monotonic):
    mock_store_cls.side_effect = ConnectionError("connection refused")
    # Two calls per loop iteration (the `while` condition, then nothing else --
    # time.sleep is NOT mocked here so make the deadline expire immediately).
    mock_monotonic.side_effect = [0.0, 100.0]

    with pytest.raises(TimeoutError):
        wait_for_neo4j_ready(timeout_s=1.0, interval_s=0.01)
