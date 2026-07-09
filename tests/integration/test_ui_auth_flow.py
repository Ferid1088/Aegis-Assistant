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
from rag.infra.stores.sql import models  # noqa: F401
from rag.infra.stores.sql.base import Base
from rag.infra.stores.sql.models import User

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

    # COOKIE_SECURE=false: this test drives the UI over plain HTTP (no TLS termination in
    # front of `next start`), and a real HTTP client enforces RFC 6265 Secure-cookie semantics
    # (unlike curl, which doesn't by default) -- without this, aegis_at/aegis_rt would be set
    # with the Secure attribute and never sent back on any subsequent request.
    ui_env = {**os.environ, "API_BASE_URL": BACKEND_URL, "COOKIE_SECURE": "false"}
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


def test_session_endpoint_reachable_through_proxy(backend_and_ui):
    session = requests.Session()
    session.post(
        f"{UI_URL}/api/auth/login",
        json={"username": "plain-user", "password": "correct-horse-battery-staple"},
    )
    resp = session.get(f"{UI_URL}/api/v1/session")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "plain-user"
    assert body["nav"]["chat"] is True
    assert body["nav"]["admin"] is False


def test_proxy_call_without_cookies_returns_401():
    resp = requests.get(f"{UI_URL}/api/v1/session")
    assert resp.status_code == 401


def test_reusing_cookies_after_logout_is_rejected(backend_and_ui):
    session = requests.Session()
    session.post(
        f"{UI_URL}/api/auth/login",
        json={"username": "plain-user", "password": "correct-horse-battery-staple"},
    )
    old_cookies = dict(session.cookies)

    session.post(f"{UI_URL}/api/auth/logout")

    stale_session = requests.Session()
    for name, value in old_cookies.items():
        stale_session.cookies.set(name, value)
    resp = stale_session.get(f"{UI_URL}/api/v1/session")
    assert resp.status_code == 401


def test_unauthenticated_chat_redirects_to_login(backend_and_ui):
    session = requests.Session()
    resp = session.get(f"{UI_URL}/chat")
    assert resp.status_code == 200  # requests follows the redirect
    assert resp.url == f"{UI_URL}/login"


def test_authenticated_chat_renders_shell_with_user_name(backend_and_ui):
    session = requests.Session()
    session.post(
        f"{UI_URL}/api/auth/login",
        json={"username": "plain-user", "password": "correct-horse-battery-staple"},
    )
    resp = session.get(f"{UI_URL}/chat")
    assert resp.status_code == 200
    assert "plain-user" in resp.text
    assert "Assistant" in resp.text


def test_sign_out_redirects_to_login_on_next_visit(backend_and_ui):
    session = requests.Session()
    session.post(
        f"{UI_URL}/api/auth/login",
        json={"username": "plain-user", "password": "correct-horse-battery-staple"},
    )
    session.post(f"{UI_URL}/api/auth/logout")
    resp = session.get(f"{UI_URL}/chat")
    assert resp.url == f"{UI_URL}/login"


def test_login_page_renders_form(backend_and_ui):
    resp = requests.get(f"{UI_URL}/login")
    assert resp.status_code == 200
    assert "Sign in to Aegis" in resp.text


@pytest.fixture(scope="module")
def short_ttl_backend_and_ui():
    engine = create_engine(settings.database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    db.add(User(username="ttl-user", password_hash=hash_password("correct-horse-battery-staple")))
    db.commit()
    db.close()
    engine.dispose()

    backend_port = BACKEND_PORT + 1
    ui_port = UI_PORT + 1
    backend_url = f"http://127.0.0.1:{backend_port}"
    ui_url = f"http://127.0.0.1:{ui_port}"

    backend_env = {**os.environ, "JWT_ACCESS_TTL_SECONDS": "5"}
    backend_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "rag.api.main:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(backend_port)],
        cwd=REPO_ROOT, env=backend_env,
    )
    _wait_for(f"{backend_url}/healthz")

    ui_env = {**os.environ, "API_BASE_URL": backend_url, "COOKIE_SECURE": "false"}
    ui_proc = subprocess.Popen(["npm", "run", "start", "--", "-p", str(ui_port)], cwd=UI_DIR, env=ui_env)
    _wait_for(ui_url)

    yield {"ui_url": ui_url}

    ui_proc.send_signal(signal.SIGTERM)
    ui_proc.wait(timeout=10)
    backend_proc.send_signal(signal.SIGTERM)
    backend_proc.wait(timeout=10)
    Base.metadata.drop_all(create_engine(settings.database_url))


def test_expired_access_token_transparently_refreshes(short_ttl_backend_and_ui):
    ui_url = short_ttl_backend_and_ui["ui_url"]
    session = requests.Session()
    session.post(f"{ui_url}/api/auth/login", json={"username": "ttl-user", "password": "correct-horse-battery-staple"})
    old_access = session.cookies.get("aegis_at")

    time.sleep(6)  # backend for this fixture was started with JWT_ACCESS_TTL_SECONDS=5

    resp = session.get(f"{ui_url}/api/v1/session")
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "ttl-user"
    assert session.cookies.get("aegis_at") != old_access


@pytest.fixture(scope="module")
def empty_backend_and_ui():
    """Same shape as `backend_and_ui` above, but seeds zero users -- this is
    what a genuinely fresh install looks like, and is what the setup wizard
    is supposed to handle."""
    engine = create_engine(settings.database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    engine.dispose()

    backend_port = BACKEND_PORT + 2
    ui_port = UI_PORT + 2
    backend_url = f"http://127.0.0.1:{backend_port}"
    ui_url = f"http://127.0.0.1:{ui_port}"

    backend_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "rag.api.main:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(backend_port)],
        cwd=REPO_ROOT,
    )
    _wait_for(f"{backend_url}/healthz")

    ui_env = {**os.environ, "API_BASE_URL": backend_url, "COOKIE_SECURE": "false"}
    ui_proc = subprocess.Popen(["npm", "run", "start", "--", "-p", str(ui_port)], cwd=UI_DIR, env=ui_env)
    _wait_for(ui_url)

    yield {"ui_url": ui_url}

    ui_proc.send_signal(signal.SIGTERM)
    ui_proc.wait(timeout=10)
    backend_proc.send_signal(signal.SIGTERM)
    backend_proc.wait(timeout=10)
    Base.metadata.drop_all(create_engine(settings.database_url))


def test_root_redirects_to_setup_when_no_admin_exists(empty_backend_and_ui):
    ui_url = empty_backend_and_ui["ui_url"]
    resp = requests.get(f"{ui_url}/chat")
    assert resp.status_code == 200  # requests follows the redirect
    assert resp.url == f"{ui_url}/setup"


def test_setup_wizard_creates_admin_and_logs_in(empty_backend_and_ui):
    ui_url = empty_backend_and_ui["ui_url"]
    session = requests.Session()

    resp = session.post(
        f"{ui_url}/api/setup",
        json={"username": "first-admin", "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "aegis_at" in session.cookies

    session_resp = session.get(f"{ui_url}/api/v1/session")
    assert session_resp.status_code == 200
    body = session_resp.json()
    assert body["user"]["username"] == "first-admin"
    assert body["nav"]["admin"] is True


def test_root_redirects_to_login_once_setup_is_done(empty_backend_and_ui):
    ui_url = empty_backend_and_ui["ui_url"]
    resp = requests.get(f"{ui_url}/chat")
    assert resp.status_code == 200
    assert resp.url == f"{ui_url}/login"


def test_visiting_setup_page_after_completion_redirects_to_login(empty_backend_and_ui):
    ui_url = empty_backend_and_ui["ui_url"]
    resp = requests.get(f"{ui_url}/setup")
    assert resp.status_code == 200
    assert resp.url == f"{ui_url}/login"
