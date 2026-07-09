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


def test_get_document_resolves_metadata_to_display_names(client, db_session):
    from rag.domain.document_lifecycle import LogicalDocument
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag import config

    dept, dtype, level = _make_metadata_rows(db_session)
    store = SQLiteDocumentStore(config.settings.sqlite_path)
    store.create_logical_document(LogicalDocument(
        logical_doc_id="doc-1", source_identity="filesystem:/x.pdf", title="Handbook",
        department=str(dept.id), document_type=str(dtype.id), access_level=[str(level.id)],
    ))
    store.create_version("doc-1", content_hash="h1", filename="x.pdf", num_pages=1)

    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    resp = client.get("/api/v1/documents/doc-1", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Handbook"
    assert body["department"] == "HR"
    assert body["department_id"] == str(dept.id)
    assert body["document_type"] == "Policy"
    assert body["document_type_id"] == str(dtype.id)
    assert body["access_level"] == "Public"
    assert body["access_level_ids"] == [str(level.id)]


def test_get_document_falls_back_for_deleted_department(client, db_session):
    from rag.domain.document_lifecycle import LogicalDocument
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag import config

    store = SQLiteDocumentStore(config.settings.sqlite_path)
    store.create_logical_document(LogicalDocument(
        logical_doc_id="doc-2", source_identity="filesystem:/y.pdf", title="Orphan",
        department="00000000-0000-0000-0000-000000000000",
    ))
    store.create_version("doc-2", content_hash="h2", filename="y.pdf", num_pages=1)

    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    resp = client.get("/api/v1/documents/doc-2", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["department"] == "Unknown department"


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
def test_upload_with_malformed_department_id_returns_4xx_not_500(mock_task, client, db_session):
    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        data={
            "title": "Test", "department_id": "not-a-uuid",
            "document_type_id": "also-not-a-uuid", "access_level_ids": ["nope"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (400, 404, 422)


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


def test_patch_metadata_updates_title_and_department(client, db_session):
    from rag.domain.document_lifecycle import LogicalDocument
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag import config

    dept, dtype, level = _make_metadata_rows(db_session)
    other_dept = Department(name="Legal")
    db_session.add(other_dept)
    db_session.flush()
    other_level = AccessLevel(department_id=other_dept.id, label="Internal", rank=1)
    db_session.add(other_level)
    db_session.commit()

    store = SQLiteDocumentStore(config.settings.sqlite_path)
    store.create_logical_document(LogicalDocument(
        logical_doc_id="doc-3", source_identity="filesystem:/z.pdf", title="Old title",
        department=str(dept.id), document_type=str(dtype.id), access_level=[str(level.id)],
    ))
    store.create_version("doc-3", content_hash="h3", filename="z.pdf", num_pages=1)

    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    resp = client.patch(
        "/api/v1/documents/doc-3/metadata",
        json={"title": "New title", "department_id": str(other_dept.id), "access_level_ids": [str(other_level.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "New title"
    assert resp.json()["department"] == "Legal"

    refetched = client.get("/api/v1/documents/doc-3", headers={"Authorization": f"Bearer {token}"})
    assert refetched.json()["title"] == "New title"


def test_patch_metadata_requires_permission(client, db_session):
    from rag.domain.document_lifecycle import LogicalDocument
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag import config

    store = SQLiteDocumentStore(config.settings.sqlite_path)
    store.create_logical_document(LogicalDocument(logical_doc_id="doc-4", source_identity="filesystem:/w.pdf"))

    _, token = _make_user_with_permission(db_session, "alice", "documents:upload")
    resp = client.patch(
        "/api/v1/documents/doc-4/metadata", json={"title": "Nope"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_patch_metadata_rejects_access_level_from_wrong_department(client, db_session):
    from rag.domain.document_lifecycle import LogicalDocument
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag import config

    dept, dtype, level = _make_metadata_rows(db_session)
    other_dept = Department(name="Legal")
    db_session.add(other_dept)
    db_session.commit()

    store = SQLiteDocumentStore(config.settings.sqlite_path)
    store.create_logical_document(LogicalDocument(
        logical_doc_id="doc-5", source_identity="filesystem:/v.pdf",
        department=str(dept.id), access_level=[str(level.id)],
    ))

    _, token = _make_user_with_permission(db_session, "alice", "documents:manage_versions")
    resp = client.patch(
        "/api/v1/documents/doc-5/metadata",
        json={"department_id": str(other_dept.id)},  # access_level_ids NOT updated -> now mismatched
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
