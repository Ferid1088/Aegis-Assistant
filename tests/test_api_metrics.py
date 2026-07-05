from fastapi.testclient import TestClient

from rag.api.main import create_app


def test_metrics_endpoint_is_scrapable():
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
