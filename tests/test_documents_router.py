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
from rag.infra.stores.sql.models import (
    AccessLevel, Department, DocumentType, Role, RolePermission, User, UserRole, UserSession,
)


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
    dept, dtype, level = _make_metadata_rows(db_session)
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Employee Handbook", "department_id": str(dept.id),
            "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
        },
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
    dept, dtype, level = _make_metadata_rows(db_session)
    job_id = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Employee Handbook", "department_id": str(dept.id),
            "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()["job_id"]

    resp = client.get(f"/api/v1/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


@patch("rag.api.routers.documents.run_ingestion")
def test_job_status_hidden_from_other_non_admin_user(mock_task, client, db_session):
    _, uploader_token = _make_user_with_permission(db_session, "alice", "documents:upload")
    dept, dtype, level = _make_metadata_rows(db_session)
    job_id = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Employee Handbook", "department_id": str(dept.id),
            "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
        },
        headers={"Authorization": f"Bearer {uploader_token}"},
    ).json()["job_id"]

    _, other_token = _make_user_with_token(db_session, "mallory")
    resp = client.get(f"/api/v1/documents/jobs/{job_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.status_code == 403


@patch("rag.api.routers.documents.run_ingestion")
def test_job_status_visible_to_admin(mock_task, client, db_session):
    _, uploader_token = _make_user_with_permission(db_session, "alice", "documents:upload")
    dept, dtype, level = _make_metadata_rows(db_session)
    job_id = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Employee Handbook", "department_id": str(dept.id),
            "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
        },
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
    dept, dtype, level = _make_metadata_rows(db_session)
    upload_data = {
        "title": "Employee Handbook", "department_id": str(dept.id),
        "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
    }

    for _ in range(5):
        resp = client.post(
            "/api/v1/documents",
            files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            data=upload_data,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data=upload_data,
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
    dept, dtype, level = _make_metadata_rows(db_session)

    with patch.object(limiter.limiter, "storage") as mock_storage:
        # patching Limiter._storage would silently no-op: the actual check path
        # reads Limiter._limiter.storage (aliased via the public `.limiter`
        # property), captured once at construction time, not `Limiter._storage`.
        mock_storage.incr.side_effect = ConnectionError("redis unreachable")
        resp = client.post(
            "/api/v1/documents",
            files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
            data={
                "title": "Employee Handbook", "department_id": str(dept.id),
                "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 202


def _make_metadata_rows(db_session):
    dept = Department(name="HR")
    db_session.add(dept)
    db_session.flush()
    dtype = DocumentType(label="Policy")
    db_session.add(dtype)
    db_session.flush()
    level = AccessLevel(department_id=dept.id, label="Public", rank=1)
    db_session.add(level)
    db_session.flush()
    db_session.commit()
    return dept, dtype, level


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_requires_metadata_fields(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_requires_access_level_ids_specifically(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    dept, dtype, level = _make_metadata_rows(db_session)
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Employee Handbook", "department_id": str(dept.id),
            "document_type_id": str(dtype.id),
            # access_level_ids deliberately omitted
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_with_valid_metadata_succeeds(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    dept, dtype, level = _make_metadata_rows(db_session)
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Employee Handbook", "department_id": str(dept.id),
            "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_with_unknown_department_404s(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    dept, dtype, level = _make_metadata_rows(db_session)
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Employee Handbook", "department_id": "00000000-0000-0000-0000-000000000000",
            "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_with_access_level_from_wrong_department_400s(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    dept, dtype, level = _make_metadata_rows(db_session)
    other_dept = Department(name="Legal")
    db_session.add(other_dept)
    db_session.commit()
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Employee Handbook", "department_id": str(other_dept.id),
            "document_type_id": str(dtype.id), "access_level_ids": [str(level.id)],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@patch("rag.api.routers.documents.run_ingestion")
def test_upload_new_version_does_not_require_metadata(mock_task, client, db_session):
    """Uploading a new version of an EXISTING document doesn't need title/department/etc.
    (the logical document already has them; only Task 7's PATCH edits them). This needs a
    user with BOTH documents:upload and documents:manage_versions, so it grants the second
    permission manually rather than using the single-permission `_make_user_with_permission`."""
    from rag.domain.document_lifecycle import LogicalDocument
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag import config
    from rag.infra.stores.sql.models import Role, RolePermission, UserRole

    store = SQLiteDocumentStore(config.settings.sqlite_path)
    store.create_logical_document(LogicalDocument(logical_doc_id="existing-doc", source_identity="filesystem:/x.pdf"))

    user, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    role = Role(name="manage-versions-too")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission="documents:manage_versions"))
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={"logical_doc_id": "existing-doc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text
