"""Requires a running Postgres: `docker compose up -d postgres` before running.
Run with: uv run pytest tests/integration/test_local_auth_flow.py -v
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rag.api.main import create_app
from rag.config import settings
from rag.crosscutting.security.password import hash_password
from rag.storage.sql import models  # noqa: F401
from rag.storage.sql.base import Base, get_db
from rag.storage.sql.models import User


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audit_log_dir", str(tmp_path))

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

    seed_db = TestSessionLocal()
    seed_db.add(User(username="alice", password_hash=hash_password("correct-horse-battery-staple")))
    seed_db.commit()
    seed_db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app, raise_server_exceptions=False)

    Base.metadata.drop_all(engine)
    engine.dispose()


def test_full_login_logout_flow_against_real_postgres(client):
    login_resp = client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-battery-staple"})
    assert login_resp.status_code == 200
    access = login_resp.json()["access_token"]

    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "alice"

    logout_resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert logout_resp.status_code == 204

    me_after_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me_after_resp.status_code == 401
