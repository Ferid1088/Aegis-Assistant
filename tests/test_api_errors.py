from fastapi.testclient import TestClient

from rag.api.main import create_app


def test_http_exception_uses_error_envelope():
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/v1/auth/me")  # no Authorization header
    assert resp.status_code == 401
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "request_id"}
    assert body["code"] == 401


def test_unhandled_exception_returns_500_envelope():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise ValueError("kaboom")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "request_id"}


def test_request_id_header_is_echoed():
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/v1/auth/me", headers={"X-Request-ID": "test-req-123"})
    assert resp.headers["X-Request-ID"] == "test-req-123"
    assert resp.json()["request_id"] == "test-req-123"
