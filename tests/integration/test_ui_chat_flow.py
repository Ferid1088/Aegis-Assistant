"""Real, non-mocked end-to-end test of the chat/conversations UI against the
real FastAPI backend and a genuinely ingested PDF. Requires:
  - `docker compose up -d postgres redis` running first.
  - The full local RAG stack (Ollama with a pulled model, Qdrant, embedding/
    reranker model weights) to actually execute ingestion and generation —
    same requirement as tests/integration/test_upload_and_chat_flow.py.
  - Node/npm on PATH (ui/ dependencies are installed automatically).
  - A real PDF fixture at docs/TV_L.pdf (gitignored, not checked in) — tests
    skip if it's absent, matching test_upload_and_chat_flow.py's convention.
Builds and starts a real Next.js production server, a real Uvicorn backend,
and a real Celery worker (matching docker-compose.yml's real `worker`
command) as subprocesses.
Run with: uv run pytest tests/integration/test_ui_chat_flow.py -v -s
"""
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rag.config import settings
from rag.crosscutting.security.password import hash_password
from rag.storage.sql import models  # noqa: F401
from rag.storage.sql.base import Base
from rag.storage.sql.models import Role, RolePermission, User, UserRole

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = REPO_ROOT / "ui"
BACKEND_PORT = 8012
UI_PORT = 3012
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
UI_URL = f"http://127.0.0.1:{UI_PORT}"
PDF_PATH = REPO_ROOT / "docs" / "TV_L.pdf"


def _wait_for(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            requests.get(url, timeout=2)
            return
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not become ready in time") from last_exc


@pytest.fixture(scope="module")
def backend_and_ui():
    engine = create_engine(settings.database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    db = session_factory()
    user = User(username="chat-user", password_hash=hash_password("correct-horse-battery-staple"))
    db.add(user)
    db.flush()
    role = Role(name="uploader")
    db.add(role)
    db.flush()
    db.add(RolePermission(role_id=role.id, permission="documents:upload"))
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    db.close()
    engine.dispose()

    backend_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "rag.api.main:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        cwd=REPO_ROOT,
    )
    _wait_for(f"{BACKEND_URL}/healthz")

    worker_proc = subprocess.Popen(
        ["uv", "run", "celery", "-A", "rag.worker.celery_app", "worker", "--loglevel=info", "--concurrency=2"],
        cwd=REPO_ROOT,
    )

    ui_env = {**os.environ, "API_BASE_URL": BACKEND_URL, "COOKIE_SECURE": "false"}
    subprocess.run(["npm", "install"], cwd=UI_DIR, check=True)
    subprocess.run(["npm", "run", "build"], cwd=UI_DIR, check=True, env=ui_env)
    ui_proc = subprocess.Popen(["npm", "run", "start", "--", "-p", str(UI_PORT)], cwd=UI_DIR, env=ui_env)
    _wait_for(UI_URL)

    yield

    for proc in (ui_proc, worker_proc, backend_proc):
        proc.send_signal(signal.SIGTERM)
    for proc in (ui_proc, worker_proc, backend_proc):
        proc.wait(timeout=15)
    Base.metadata.drop_all(create_engine(settings.database_url))


@pytest.fixture(scope="module")
def chat_session(backend_and_ui):
    """Logs in once and uploads docs/TV_L.pdf once (waiting for it to finish
    indexing), shared by both tests below since real ingestion is expensive."""
    session = requests.Session()
    login = session.post(
        f"{UI_URL}/api/auth/login",
        json={"username": "chat-user", "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200, login.text

    with open(PDF_PATH, "rb") as f:
        upload = session.post(f"{UI_URL}/api/v1/documents", files={"file": ("TV_L.pdf", f, "application/pdf")})
    assert upload.status_code == 202, upload.text
    job_id = upload.json()["job_id"]

    status = None
    for _ in range(120):
        status_resp = session.get(f"{UI_URL}/api/v1/documents/jobs/{job_id}")
        assert status_resp.status_code == 200, status_resp.text
        status = status_resp.json()["status"]
        if status in ("done", "failed"):
            break
        time.sleep(1)
    assert status == "done", f"ingestion job did not complete successfully: {status}"

    return session


@pytest.mark.skipif(not PDF_PATH.exists(), reason=f"requires a real PDF fixture at {PDF_PATH} (gitignored, not checked in)")
def test_chat_answerable_query_returns_enriched_answer_and_citations(chat_session):
    conv = chat_session.post(f"{UI_URL}/api/v1/conversations")
    assert conv.status_code == 201, conv.text
    conv_id = conv.json()["id"]

    resp = chat_session.post(
        f"{UI_URL}/api/v1/conversations/{conv_id}/messages",
        json={"question": "Was ist die Grundvergütung in E5?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] in ("answerable", "assumption")
    assert body["answer"]
    assert len(body["citations"]) > 0
    citation = body["citations"][0]
    assert citation["documentTitle"] and citation["documentTitle"] != "(unknown document)"
    assert citation["page"] >= 1

    listing = chat_session.get(f"{UI_URL}/api/v1/conversations")
    assert listing.status_code == 200, listing.text
    summary = next(c for c in listing.json() if c["id"] == conv_id)
    assert summary["messageCount"] == 1
    assert summary["title"] == "Was ist die Grundvergütung in E5?"
    assert summary["locked"] is False


@pytest.mark.skipif(not PDF_PATH.exists(), reason=f"requires a real PDF fixture at {PDF_PATH} (gitignored, not checked in)")
def test_chat_off_topic_query_hits_gate(chat_session):
    conv = chat_session.post(f"{UI_URL}/api/v1/conversations")
    assert conv.status_code == 201, conv.text
    conv_id = conv.json()["id"]

    resp = chat_session.post(
        f"{UI_URL}/api/v1/conversations/{conv_id}/messages",
        json={"question": "What is the capital of France?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] in ("unanswerable", "clarification")
    assert body["citations"] == []
    if body["verdict"] == "unanswerable":
        assert body["unanswerableReason"]
    else:
        assert body["clarificationQuestion"]
