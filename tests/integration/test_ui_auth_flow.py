"""Real, non-mocked end-to-end test of the Next.js auth BFF against the real
FastAPI backend. Requires:
  - `docker compose up -d postgres redis` running first.
  - Node/npm on PATH (ui/ dependencies are installed automatically).
Builds and starts both the backend (uvicorn) and the frontend (next build +
next start) as subprocesses and drives them with real HTTP requests.
Run with: uv run pytest tests/integration/test_ui_auth_flow.py -v
"""
import os
import signal
import subprocess
import time
from pathlib import Path

import pyotp
import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rag.config import settings
from rag.crosscutting.security.mfa import encrypt_secret
from rag.crosscutting.security.password import hash_password
from rag.storage.sql import models  # noqa: F401
from rag.storage.sql.base import Base
from rag.storage.sql.models import User

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = REPO_ROOT / "ui"
BACKEND_PORT = 8011
UI_PORT = 3011
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
UI_URL = f"http://127.0.0.1:{UI_PORT}"


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
    db.add(User(username="plain-user", password_hash=hash_password("correct-horse-battery-staple")))

    mfa_secret = pyotp.random_base32()
    db.add(User(
        username="mfa-user", password_hash=hash_password("correct-horse-battery-staple"),
        mfa_enabled=True, mfa_secret_encrypted=encrypt_secret(db, mfa_secret),
    ))
    db.commit()
    db.close()
    engine.dispose()

    backend_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "rag.api.main:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        cwd=REPO_ROOT,
    )
    _wait_for(f"{BACKEND_URL}/healthz")

    ui_env = {**os.environ, "API_BASE_URL": BACKEND_URL}
    subprocess.run(["npm", "install"], cwd=UI_DIR, check=True)
    subprocess.run(["npm", "run", "build"], cwd=UI_DIR, check=True, env=ui_env)
    ui_proc = subprocess.Popen(["npm", "run", "start", "--", "-p", str(UI_PORT)], cwd=UI_DIR, env=ui_env)
    _wait_for(UI_URL)

    yield {"mfa_secret": mfa_secret}

    ui_proc.send_signal(signal.SIGTERM)
    ui_proc.wait(timeout=10)
    backend_proc.send_signal(signal.SIGTERM)
    backend_proc.wait(timeout=10)
    Base.metadata.drop_all(create_engine(settings.database_url))


def test_login_wrong_password_returns_401(backend_and_ui):
    session = requests.Session()
    resp = session.post(f"{UI_URL}/api/auth/login", json={"username": "plain-user", "password": "wrong"})
    assert resp.status_code == 401
    assert "aegis_at" not in session.cookies


def test_login_success_sets_cookies(backend_and_ui):
    session = requests.Session()
    resp = session.post(
        f"{UI_URL}/api/auth/login",
        json={"username": "plain-user", "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "aegis_at" in session.cookies
    assert "aegis_rt" in session.cookies


def test_mfa_login_flow(backend_and_ui):
    session = requests.Session()
    login_resp = session.post(
        f"{UI_URL}/api/auth/login",
        json={"username": "mfa-user", "password": "correct-horse-battery-staple"},
    )
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["mfa_required"] is True
    pending_token = body["mfa_pending_token"]
    assert "aegis_at" not in session.cookies

    wrong = session.post(
        f"{UI_URL}/api/auth/mfa-verify", json={"mfa_pending_token": pending_token, "totp_code": "000000"}
    )
    assert wrong.status_code == 401
    assert "aegis_at" not in session.cookies

    code = pyotp.TOTP(backend_and_ui["mfa_secret"]).now()
    correct = session.post(
        f"{UI_URL}/api/auth/mfa-verify", json={"mfa_pending_token": pending_token, "totp_code": code}
    )
    assert correct.status_code == 200
    assert "aegis_at" in session.cookies


def test_logout_clears_cookies(backend_and_ui):
    session = requests.Session()
    session.post(
        f"{UI_URL}/api/auth/login",
        json={"username": "plain-user", "password": "correct-horse-battery-staple"},
    )
    assert "aegis_at" in session.cookies

    logout_resp = session.post(f"{UI_URL}/api/auth/logout")
    assert logout_resp.status_code == 200
    assert session.cookies.get("aegis_at") in (None, "")
