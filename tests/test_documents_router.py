import io
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.api.routers import documents
from rag.crosscutting.security.rate_limit import limiter
from rag.crosscutting.security.tokens import create_access_token
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import AccessLevel, Department, DocumentType, Role, RolePermission, User, UserRole, UserSession


def _make_user_with_token(db_session, username):
    user = User(username=username)
    db_session.add(user)
    db_session.flush()
    session = UserSession(
        user_id=user.id, issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(session)
    db_session.commit()
    token = create_access_token(str(user.id), str(session.id), user.token_version)
    return user, token


def _make_user_with_permission(db_session, username, permission):
    user, token = _make_user_with_token(db_session, username)
    role = Role(name=f"role-{permission}-{username}")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission=permission))
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user, token


@pytest.fixture()
def client(db_session, tmp_path, monkeypatch):
    from rag import config
    monkeypatch.setattr(config.settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(config.settings, "sqlite_path", str(tmp_path / "documents.db"))

    app = FastAPI()
    app.state.limiter = limiter
    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(documents.router, prefix="/api/v1/documents")
    return TestClient(app, raise_server_exceptions=False)


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_requires_permission(mock_task, client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_enqueues_job_and_returns_job_id(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    assert "job_id" in resp.json()
    mock_task.delay.assert_called_once()


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_rejects_non_pdf(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.txt", io.BytesIO(b"not a pdf"), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 415


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_rejects_oversized_file(mock_task, client, db_session, monkeypatch):
    from rag import config
    monkeypatch.setattr(config.settings, "max_upload_bytes", 10)
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 more than ten bytes"), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413
    mock_task.delay.assert_not_called()


def test_job_status_unknown_id_404s(client, db_session):
    import uuid
    _, token = _make_user_with_token(db_session, "alice")
    resp = client.get(f"/api/v1/documents/jobs/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


def test_get_document_unknown_id_404s(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    resp = client.get("/api/v1/documents/not-a-real-id", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


@patch("rag.api.routers.documents.run_ingestion")
def test_job_status_visible_to_uploader(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    job_id = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["job_id"]

    resp = client.get(f"/api/v1/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


@patch("rag.api.routers.documents.run_ingestion")
def test_job_status_hidden_from_other_non_admin_user(mock_task, client, db_session):
    _, uploader_token = _make_user_with_permission(db_session, "alice", "documents:upload")
    job_id = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers={"Authorization": f"Bearer {uploader_token}"},
    ).json()["job_id"]

    _, other_token = _make_user_with_token(db_session, "mallory")
    resp = client.get(f"/api/v1/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.status_code == 403


@patch("rag.api.routers.documents.run_ingestion")
def test_job_status_visible_to_admin(mock_task, client, db_session):
    _, uploader_token = _make_user_with_permission(db_session, "alice", "documents:upload")
    job_id = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers={"Authorization": f"Bearer {uploader_token}"},
    ).json()["job_id"]

    _, admin_token = _make_user_with_permission(db_session, "admin", "admin:documents")
    resp = client.get(f"/api/v1/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200


def test_list_documents_empty(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_returns_429_after_the_rate_limit_is_exceeded(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")

    for _ in range(5):
        resp = client.post(
            "/api/v1/documents",
            files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 429


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_still_succeeds_when_the_rate_limit_backend_is_unreachable(mock_task, client, db_session):
    # swallow_errors=True (rate_limit.py) means a Redis connection failure logs a
    # warning and lets the request through, rather than crashing the whole upload
    # with an unhandled 500 -- this proves that fail-open behavior end-to-end
    # through the real route, not just by inspecting the Limiter's configuration.
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")

    with patch.object(limiter.limiter, "storage") as mock_storage:
        # patching Limiter._storage would silently no-op: the actual check path
        # reads Limiter._limiter.storage (aliased via the public `.limiter`
        # property), captured once at construction time, not `Limiter._storage`.
        mock_storage.incr.side_effect = ConnectionError("redis unreachable")
        resp = client.post(
            "/api/v1/documents",
            files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 202


def _make_department(db_session, name="Finance"):
    dept = Department(name=name)
    db_session.add(dept)
    db_session.commit()
    return dept


def _make_document_type(db_session, label="invoice"):
    dt = DocumentType(label=label)
    db_session.add(dt)
    db_session.commit()
    return dt


def _make_access_level(db_session, department, label="FIN_L1", rank=1):
    level = AccessLevel(department_id=department.id, label=label, rank=rank)
    db_session.add(level)
    db_session.commit()
    return level


@patch("rag.api.routers.documents.run_ingestion")
def _upload_document(mock_task, client, token):
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["job_id"]


def test_patch_metadata_requires_permission(client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    resp = client.patch(
        "/api/v1/documents/does-not-exist", json={"department": "Finance"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_patch_metadata_valid_update(client, db_session):
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag.domain.document_lifecycle import LogicalDocument

    dept = _make_department(db_session)
    _make_document_type(db_session)
    _make_access_level(db_session, dept)

    store = SQLiteDocumentStore()
    store.create_logical_document(LogicalDocument(logical_doc_id="L1", source_identity="manual:L1"))

    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    resp = client.patch(
        "/api/v1/documents/L1",
        json={"department": "Finance", "document_type": "invoice", "access_level": ["FIN_L1"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["department"] == "Finance"
    assert body["document_type"] == "invoice"
    assert body["access_level"] == "FIN_L1"


def test_patch_metadata_unknown_department_404s(client, db_session):
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag.domain.document_lifecycle import LogicalDocument

    store = SQLiteDocumentStore()
    store.create_logical_document(LogicalDocument(logical_doc_id="L2", source_identity="manual:L2"))

    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    resp = client.patch(
        "/api/v1/documents/L2", json={"department": "NoSuchDept"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_patch_metadata_invalid_access_level_for_department_422s(client, db_session):
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag.domain.document_lifecycle import LogicalDocument

    dept = _make_department(db_session, "HR")
    _make_access_level(db_session, dept, "HR_L1")
    other_dept = _make_department(db_session, "Legal")
    _make_access_level(db_session, other_dept, "LEGAL_L1")

    store = SQLiteDocumentStore()
    store.create_logical_document(LogicalDocument(logical_doc_id="L3", source_identity="manual:L3"))

    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    resp = client.patch(
        "/api/v1/documents/L3",
        json={"department": "HR", "access_level": ["LEGAL_L1"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_patch_metadata_clearing_department_requires_empty_access_level(client, db_session):
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag.domain.document_lifecycle import LogicalDocument

    dept = _make_department(db_session)
    _make_access_level(db_session, dept)

    store = SQLiteDocumentStore()
    store.create_logical_document(
        LogicalDocument(logical_doc_id="L4", source_identity="manual:L4", department="Finance", access_level=["FIN_L1"])
    )

    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    resp = client.patch(
        "/api/v1/documents/L4", json={"department": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

    resp = client.patch(
        "/api/v1/documents/L4", json={"department": None, "access_level": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["department"] is None


def _add_second_permission(db_session, username, permission):
    """_make_user_with_permission grants exactly one permission via one role;
    these tests need a user with two, so this grants a second one the same way."""
    role = Role(name=f"role-{permission}-{username}-2")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission=permission))
    user = db_session.query(User).filter_by(username=username).one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_with_metadata_by_manager(mock_task, client, db_session):
    dept = _make_department(db_session)
    _make_access_level(db_session, dept)
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    _add_second_permission(db_session, "alice", "documents:manage_versions")

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={"department": "Finance", "access_level": "FIN_L1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_with_metadata_rejected_without_manage_permission(mock_task, client, db_session):
    _make_department(db_session)
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={"department": "Finance"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_with_unknown_department_404s(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    _add_second_permission(db_session, "alice", "documents:upload")

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={"department": "NoSuchDept"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
