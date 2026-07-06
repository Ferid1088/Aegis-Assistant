from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from rag.api.main import create_app


@patch("rag.observability.queue_metrics.redis.Redis.from_url")
def test_metrics_endpoint_is_scrapable(mock_from_url):
    # rag.api.main transitively imports rag.worker.celery_app (via the documents
    # router -> rag.worker.tasks), which -- if settings.redis_url is set -- already
    # bound celery_queue_depth's scrape function to a real redis.Redis client at
    # collection time, in whatever environment this test session's settings.redis_url
    # pointed at (e.g. a Docker-Compose-only hostname unreachable from the test host).
    # Re-run _update_queue_depth() with a mocked client so /metrics' scrape doesn't
    # depend on a real, reachable Redis -- same idiom as
    # test_update_queue_depth_reflects_the_real_llen in
    # test_observability_queue_metrics.py.
    mock_client = MagicMock()
    mock_client.llen.return_value = 0
    mock_from_url.return_value = mock_client
    from rag.observability.queue_metrics import _update_queue_depth
    _update_queue_depth()

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    client.get("/healthz")  # generate at least one request so metrics aren't empty

    resp = client.get("/metrics")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    # prometheus-fastapi-instrumentator's metrics use the "http_" prefix convention --
    # confirms real instrumentation output, not an empty/placeholder response. Verify
    # the exact metric name(s) empirically (read the real response body) if a later
    # task needs to reference one precisely -- see this plan's Global Constraints.
    assert "http_" in resp.text
