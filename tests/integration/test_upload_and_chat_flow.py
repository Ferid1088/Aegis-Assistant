"""End-to-end integration test: upload a PDF, let it index, then chat about it.

Requires a running Postgres and Redis: `docker compose up -d postgres redis` before running.
Also requires the full local RAG stack (Ollama with a pulled model, Qdrant, embedding/reranker
model weights) to actually execute ingestion and generation — the same requirement as the
existing `run_ingest.py` / `run_query.py` CLIs. Celery runs in eager/synchronous mode so no
separate worker process is needed.

Run with: uv run pytest tests/integration/test_upload_and_chat_flow.py -v -s
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rag.api.main import create_app
from rag.config import settings
from rag.crosscutting.security.tokens import create_access_token
from rag.infra.stores.sql import models  # noqa: F401  (registers models on Base.metadata)
from rag.infra.stores.sql.base import Base, get_db
from rag.infra.stores.sql.models import Role, RolePermission, User, UserRole, UserSession
from rag.worker.celery_app import celery_app

PDF_PATH = "docs/TV_L.pdf"


@pytest.fixture(autouse=True, scope="module")
def _eager_celery():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Mirrors tests/integration/test_local_auth_flow.py's real-Postgres fixture pattern:
    a fresh engine against settings.database_url, tables created/dropped per test, and
    get_db overridden on an app built via create_app() (so both routers + prefixes match
    production wiring exactly)."""
    monkeypatch.setattr(settings, "audit_log_dir", str(tmp_path))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    engine = create_engine(settings.database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app, raise_server_exceptions=False), TestSessionLocal

    Base.metadata.drop_all(engine)
    engine.dispose()


def _make_authorized_user(session_factory, username, permission):
    db = session_factory()
    try:
        user = User(username=username)
        db.add(user)
        db.flush()
        role = Role(name=f"role-{permission}-{username}")
        db.add(role)
        db.flush()
        db.add(RolePermission(role_id=role.id, permission=permission))
        db.add(UserRole(user_id=user.id, role_id=role.id))
        user_session = UserSession(
            user_id=user.id, issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(user_session)
        db.commit()
        token = create_access_token(str(user.id), str(user_session.id), user.token_version)
        return user, token
    finally:
        db.close()


@pytest.mark.skipif(not os.path.exists(PDF_PATH), reason=f"requires a real PDF fixture at {PDF_PATH} (gitignored, not checked in)")
def test_upload_index_and_chat_round_trip(client):
    test_client, session_factory = client

    _, token = _make_authorized_user(session_factory, "integration-uploader", "documents:upload")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload a real PDF -> should enqueue an ingestion job (202) and, under eager Celery,
    # the job should already have run synchronously by the time upload_document returns.
    with open(PDF_PATH, "rb") as f:
        resp = test_client.post(
            "/api/v1/documents",
            files={"file": ("TV_L.pdf", f, "application/pdf")},
            headers=headers,
        )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    # 2. Poll job status until it reaches a terminal state (allow for real embedding/indexing time).
    status = None
    for _ in range(120):
        status_resp = test_client.get(f"/api/v1/documents/jobs/{job_id}", headers=headers)
        assert status_resp.status_code == 200, status_resp.text
        status = status_resp.json()["status"]
        if status in ("done", "failed"):
            break
        import time
        time.sleep(1)
    assert status == "done", f"ingestion job did not complete successfully: {status}"

    # 3. The ingested document should now be listed.
    docs_resp = test_client.get("/api/v1/documents", headers=headers)
    assert docs_resp.status_code == 200, docs_resp.text
    assert len(docs_resp.json()) >= 1

    # 4. Create a conversation and ask a question grounded in the ingested document; expect
    # a real, non-empty answer produced by the full query graph (retrieval + generation).
    conv_resp = test_client.post("/api/v1/conversations", headers=headers)
    assert conv_resp.status_code == 201, conv_resp.text
    conv_id = conv_resp.json()["id"]

    chat_resp = test_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"question": "Was ist die Grundvergütung in E5?"},
        headers=headers,
    )
    assert chat_resp.status_code == 200, chat_resp.text
    body = chat_resp.json()
    assert body["answer"]
    assert body["turn_index"] == 1  # first turn: next_index = coalesce(max(turn_index), 0) + 1
