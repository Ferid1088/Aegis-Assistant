from unittest.mock import patch

from rag.crosscutting.security.generation_limits import (
    check_and_increment_inflight_generation, decrement_inflight_generation,
)


@patch("rag.crosscutting.security.generation_limits._redis_client")
def test_allows_when_under_the_threshold(mock_client):
    mock_client.incr.return_value = 3

    allowed = check_and_increment_inflight_generation(max_inflight=20)

    assert allowed is True
    mock_client.incr.assert_called_once_with("generation_inflight")


@patch("rag.crosscutting.security.generation_limits._redis_client")
def test_rejects_and_decrements_when_over_the_threshold(mock_client):
    mock_client.incr.return_value = 21

    allowed = check_and_increment_inflight_generation(max_inflight=20)

    assert allowed is False
    mock_client.decr.assert_called_once_with("generation_inflight")


@patch("rag.crosscutting.security.generation_limits._redis_client")
def test_decrement_calls_redis_decr(mock_client):
    decrement_inflight_generation()

    mock_client.decr.assert_called_once_with("generation_inflight")


@patch("rag.crosscutting.security.generation_limits._redis_client")
def test_check_and_increment_sets_a_ttl_backstop_on_the_counter(mock_client):
    mock_client.incr.return_value = 1

    check_and_increment_inflight_generation(max_inflight=20)

    mock_client.expire.assert_called_once()
    args, _ = mock_client.expire.call_args
    assert args[0] == "generation_inflight"
    assert args[1] > 0


def test_fails_open_when_redis_unavailable(monkeypatch):
    import rag.crosscutting.security.generation_limits as gl
    monkeypatch.setattr(gl, "_redis_client", None)

    assert gl.check_and_increment_inflight_generation(max_inflight=20) is True
    gl.decrement_inflight_generation()  # must not raise
