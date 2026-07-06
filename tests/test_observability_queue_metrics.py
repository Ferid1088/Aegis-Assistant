from unittest.mock import MagicMock, patch


@patch("rag.observability.queue_metrics.redis.Redis.from_url")
def test_update_queue_depth_reflects_the_real_llen(mock_from_url):
    from rag.observability.queue_metrics import QUEUE_DEPTH, _update_queue_depth

    mock_client = MagicMock()
    mock_client.llen.return_value = 7
    mock_from_url.return_value = mock_client

    _update_queue_depth()

    assert QUEUE_DEPTH.collect()[0].samples[0].value == 7
    mock_client.llen.assert_called_with("celery")


@patch("rag.observability.queue_metrics.start_http_server")
@patch("rag.observability.queue_metrics._update_queue_depth")
def test_start_queue_depth_exporter_starts_server_on_the_documented_port(mock_update, mock_start_server):
    from rag.observability.queue_metrics import start_queue_depth_exporter

    start_queue_depth_exporter()

    mock_update.assert_called_once()
    mock_start_server.assert_called_once_with(9540)


@patch("rag.worker.celery_app.start_queue_depth_exporter")
def test_maybe_start_queue_depth_exporter_starts_when_redis_url_is_set(mock_start, monkeypatch):
    from rag.config import settings
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379")

    from rag.worker.celery_app import _maybe_start_queue_depth_exporter
    _maybe_start_queue_depth_exporter()

    mock_start.assert_called_once()


@patch("rag.worker.celery_app.start_queue_depth_exporter")
def test_maybe_start_queue_depth_exporter_skips_when_redis_url_is_empty(mock_start, monkeypatch):
    from rag.config import settings
    monkeypatch.setattr(settings, "redis_url", "")

    from rag.worker.celery_app import _maybe_start_queue_depth_exporter
    _maybe_start_queue_depth_exporter()

    mock_start.assert_not_called()
