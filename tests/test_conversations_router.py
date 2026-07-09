from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.api.routers import conversations
from rag.crosscutting.security.tokens import create_access_token
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import Role, RolePermission, User, UserRole, UserSession


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


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(conversations.router, prefix="/api/v1/conversations")
    return TestClient(app, raise_server_exceptions=False)


def test_create_and_get_conversation(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/v1/conversations", headers=headers)
    assert resp.status_code == 201
    conv_id = resp.json()["id"]
    assert resp.json()["state"] == "active"

    resp = client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == conv_id


def test_get_conversation_not_owned_by_caller_404s(client, db_session):
    _, alice_token = _make_user_with_token(db_session, "alice")
    _, mallory_token = _make_user_with_token(db_session, "mallory")

    resp = client.post("/api/v1/conversations", headers={"Authorization": f"Bearer {alice_token}"})
    conv_id = resp.json()["id"]

    resp = client.get(f"/api/v1/conversations/{conv_id}", headers={"Authorization": f"Bearer {mallory_token}"})
    assert resp.status_code == 404


def test_list_conversations_returns_only_callers_own(client, db_session):
    _, alice_token = _make_user_with_token(db_session, "alice")
    _, mallory_token = _make_user_with_token(db_session, "mallory")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    client.post("/api/v1/conversations", headers=alice_headers)
    client.post("/api/v1/conversations", headers=alice_headers)
    client.post("/api/v1/conversations", headers={"Authorization": f"Bearer {mallory_token}"})

    resp = client.get("/api/v1/conversations", headers=alice_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_transition_conversation(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    resp = client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "archived"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "archived"


def test_transition_to_invalid_state_name_422s(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    resp = client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "not-a-real-state"}, headers=headers)
    assert resp.status_code == 422


def test_transition_disallowed_by_state_machine_409s(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    resp = client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "purged"}, headers=headers)
    assert resp.status_code == 409


def test_erasure_request_purges(client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]
    client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "soft_deleted"}, headers=headers)

    resp = client.post(f"/api/v1/conversations/{conv_id}/erasure-request", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["action"] == "purge"

    resp = client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert resp.json()["state"] == "purged"


def test_endpoints_require_authentication(client, db_session):
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 401


def _make_admin_with_token(db_session, permission="admin:conversations"):
    admin, token = _make_user_with_token(db_session, "admin")
    role = Role(name=f"role-{permission}")
    db_session.add(role)
    db_session.flush()
    db_session.add(RolePermission(role_id=role.id, permission=permission))
    db_session.add(UserRole(user_id=admin.id, role_id=role.id))
    db_session.commit()
    return admin, token


def test_admin_can_set_legal_hold_on_any_conversation(client, db_session):
    _, owner_token = _make_user_with_token(db_session, "alice")
    _, admin_token = _make_admin_with_token(db_session)
    conv_id = client.post("/api/v1/conversations", headers={"Authorization": f"Bearer {owner_token}"}).json()["id"]

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/legal-hold", json={"hold": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["legal_hold"] is True


def test_owner_without_admin_permission_cannot_set_legal_hold(client, db_session):
    _, owner_token = _make_user_with_token(db_session, "alice")
    conv_id = client.post("/api/v1/conversations", headers={"Authorization": f"Bearer {owner_token}"}).json()["id"]

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/legal-hold", json={"hold": True},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 403


def test_legal_hold_blocks_owners_own_erasure_request(client, db_session):
    _, owner_token = _make_user_with_token(db_session, "alice")
    _, admin_token = _make_admin_with_token(db_session)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    conv_id = client.post("/api/v1/conversations", headers=owner_headers).json()["id"]

    client.post(
        f"/api/v1/conversations/{conv_id}/legal-hold", json={"hold": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    resp = client.post(f"/api/v1/conversations/{conv_id}/erasure-request", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.json()["action"] == "refuse"

    check = client.get(f"/api/v1/conversations/{conv_id}", headers=owner_headers)
    assert check.json()["state"] == "active"


@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_returns_answer_and_persists_turn(mock_build_graph, client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {
        "answer": "42", "citations": [{"chunk_id": "c0", "page_numbers": [1]}],
        "standalone_question": "What is the answer?", "turn_history": [],
    }

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"question": "What is the answer?"}, headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["answer"] == "42"
    assert resp.json()["turnIndex"] == 1

    listing = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert listing.json()[0]["question"] == "What is the answer?"

    assert mock_graph.invoke.call_args.kwargs["config"] == {
        "configurable": {"thread_id": str(conv_id)},
    }


@patch("rag.api.routers.conversations.decrement_inflight_generation")
@patch("rag.api.routers.conversations.check_and_increment_inflight_generation", return_value=False)
@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_rejected_when_generation_cap_reached(
    mock_build_graph, mock_check, mock_decrement, client, db_session,
):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"question": "hi"}, headers=headers,
    )

    assert resp.status_code == 429
    mock_build_graph.assert_not_called()
    mock_decrement.assert_not_called()  # never incremented, so must not decrement either


@patch("rag.api.routers.conversations.decrement_inflight_generation")
@patch("rag.api.routers.conversations.check_and_increment_inflight_generation", return_value=True)
@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_decrements_generation_counter_on_success(
    mock_build_graph, mock_check, mock_decrement, client, db_session,
):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    mock_build_graph.return_value.invoke.return_value = {
        "answer": "42", "citations": [], "standalone_question": "hi", "turn_history": [],
    }

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"question": "hi"}, headers=headers,
    )

    assert resp.status_code == 200
    mock_decrement.assert_called_once()


@patch("rag.api.routers.conversations.decrement_inflight_generation")
@patch("rag.api.routers.conversations.check_and_increment_inflight_generation", return_value=True)
@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_decrements_generation_counter_even_when_graph_raises(
    mock_build_graph, mock_check, mock_decrement, client, db_session,
):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    mock_build_graph.return_value.invoke.side_effect = RuntimeError("LLM backend unreachable")

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"question": "hi"}, headers=headers,
    )

    assert resp.status_code == 500
    mock_decrement.assert_called_once()


@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_rejected_when_conversation_not_active(mock_build_graph, client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]
    client.post(f"/api/v1/conversations/{conv_id}/transition", json={"target_state": "locked"}, headers=headers)

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"question": "hi"}, headers=headers,
    )
    assert resp.status_code == 409
    mock_build_graph.assert_not_called()


@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_not_owned_404s(mock_build_graph, client, db_session):
    _, alice_token = _make_user_with_token(db_session, "alice")
    _, mallory_token = _make_user_with_token(db_session, "mallory")
    conv_id = client.post(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {alice_token}"},
    ).json()["id"]

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"question": "hi"},
        headers={"Authorization": f"Bearer {mallory_token}"},
    )
    assert resp.status_code == 404


@patch("rag.api.routers.conversations.build_query_graph")
def test_second_message_uses_persisted_history(mock_build_graph, client, db_session):
    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {
        "answer": "a1", "citations": [], "standalone_question": "q1", "turn_history": [],
    }
    client.post(f"/api/v1/conversations/{conv_id}/messages", json={"question": "q1"}, headers=headers)

    mock_graph.invoke.return_value = {
        "answer": "a2", "citations": [], "standalone_question": "q2 standalone", "turn_history": [],
    }
    client.post(f"/api/v1/conversations/{conv_id}/messages", json={"question": "q2"}, headers=headers)

    invoked_state = mock_graph.invoke.call_args.args[0]
    assert len(invoked_state["turn_history"]) == 1
    assert invoked_state["turn_history"][0]["user_question"] == "q1"


@patch("rag.api.routers.conversations.check_and_increment_inflight_generation", return_value=True)
@patch("rag.api.routers.conversations.decrement_inflight_generation")
@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_surfaces_verdict_and_enriched_citations(
    mock_build_graph, mock_decrement, mock_check, client, db_session, tmp_path, monkeypatch,
):
    from rag.config import settings
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "documents.db"))
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag.domain.document_lifecycle import LogicalDocument

    store = SQLiteDocumentStore()
    store.create_logical_document(LogicalDocument(logical_doc_id="doc-1", source_identity="/mnt/docs/report.pdf"))
    store.create_version("doc-1", content_hash="hash1", filename="report.pdf", num_pages=10)

    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {
        "answer": "42", "standalone_question": "What is the answer?", "turn_history": [],
        "answerability_verdict": "assumption",
        "assumptions": ["Assuming the standard case."],
        "clarification_question": None,
        "unanswerable_reason": None,
        "citations": [{"chunk_id": "c1", "page_numbers": [7], "section": [], "bboxes": [],
                       "logical_doc_id": "doc-1"}],
    }

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"question": "What is the answer?"}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "assumption"
    assert body["assumptions"] == ["Assuming the standard case."]
    assert body["clarificationQuestion"] is None
    assert body["unanswerableReason"] is None
    citation = body["citations"][0]
    assert citation["documentId"] == "doc-1"
    assert citation["documentTitle"] == "report"
    assert citation["versionNo"] == 1
    assert citation["page"] == 7


@patch("rag.api.routers.conversations.check_and_increment_inflight_generation", return_value=True)
@patch("rag.api.routers.conversations.decrement_inflight_generation")
@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_citation_region_uses_real_bbox_dict_shape(
    mock_build_graph, mock_decrement, mock_check, client, db_session, tmp_path, monkeypatch,
):
    from rag.config import settings
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "documents.db"))
    from rag.infra.stores.document_store import SQLiteDocumentStore
    from rag.domain.document_lifecycle import LogicalDocument

    store = SQLiteDocumentStore()
    store.create_logical_document(LogicalDocument(logical_doc_id="doc-1", source_identity="/mnt/docs/report.pdf"))
    store.create_version("doc-1", content_hash="hash1", filename="report.pdf", num_pages=10)

    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {
        "answer": "42", "standalone_question": "What is the answer?", "turn_history": [],
        "citations": [{
            "chunk_id": "c1", "page_numbers": [1], "section": [],
            "bboxes": [{"page": 1, "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}],
            "logical_doc_id": "doc-1",
        }],
    }

    resp = client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"question": "What is the answer?"}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["citations"][0]["region"] == [0.1, 0.2, 0.3, 0.4]


@patch("rag.api.routers.conversations.check_and_increment_inflight_generation", return_value=True)
@patch("rag.api.routers.conversations.decrement_inflight_generation")
@patch("rag.api.routers.conversations.build_query_graph")
def test_post_message_citation_for_unresolvable_document_degrades_gracefully(
    mock_build_graph, mock_decrement, mock_check, client, db_session, tmp_path, monkeypatch,
):
    from rag.config import settings
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "documents.db"))

    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {
        "answer": "42", "standalone_question": "q", "turn_history": [],
        "citations": [{"chunk_id": "c1", "page_numbers": [1], "section": [], "bboxes": [],
                       "logical_doc_id": "does-not-exist"}],
    }

    resp = client.post(f"/api/v1/conversations/{conv_id}/messages", json={"question": "q"}, headers=headers)
    assert resp.status_code == 200, resp.text
    citation = resp.json()["citations"][0]
    assert citation["documentTitle"] == "(unknown document)"
    assert citation["versionNo"] == 0


def test_list_conversations_excludes_soft_deleted_and_purged(client, db_session):
    import uuid as uuid_module

    from rag.domain.conversation import ConversationState
    from rag.infra.stores.sql.models import Conversation

    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}

    active_id = client.post("/api/v1/conversations", headers=headers).json()["id"]
    deleted_id = client.post("/api/v1/conversations", headers=headers).json()["id"]

    conv = db_session.get(Conversation, uuid_module.UUID(deleted_id))
    conv.state = ConversationState.SOFT_DELETED.value
    db_session.commit()

    resp = client.get("/api/v1/conversations", headers=headers)
    assert resp.status_code == 200, resp.text
    ids = [c["id"] for c in resp.json()]
    assert active_id in ids
    assert deleted_id not in ids


def test_list_conversations_computes_title_updated_at_message_count_locked(client, db_session):
    import uuid as uuid_module

    from rag.domain.conversation import ConversationState
    from rag.infra.stores.sql.models import Conversation

    _, token = _make_user_with_token(db_session, "alice")
    headers = {"Authorization": f"Bearer {token}"}

    empty_id = client.post("/api/v1/conversations", headers=headers).json()["id"]
    resp = client.get("/api/v1/conversations", headers=headers)
    empty_summary = next(c for c in resp.json() if c["id"] == empty_id)
    assert empty_summary["title"] == "New conversation"
    assert empty_summary["messageCount"] == 0
    assert empty_summary["locked"] is False

    locked_id = client.post("/api/v1/conversations", headers=headers).json()["id"]
    conv = db_session.get(Conversation, uuid_module.UUID(locked_id))
    conv.state = ConversationState.LOCKED.value
    db_session.commit()
    resp2 = client.get("/api/v1/conversations", headers=headers)
    locked_summary = next(c for c in resp2.json() if c["id"] == locked_id)
    assert locked_summary["locked"] is True
