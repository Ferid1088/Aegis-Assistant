from rag.crosscutting.security import audit_events
from rag.crosscutting.security.audit import AuditLog


def test_record_login_success_appends_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr("rag.config.settings.audit_log_dir", str(tmp_path))

    audit_events.record_login_success("user-1", request_id="req-1", ip="127.0.0.1")

    log = AuditLog(log_dir=str(tmp_path))
    assert log.count() == 1
    valid, count, error = log.verify_chain()
    assert valid is True
    assert count == 1
    assert error == ""


def test_record_login_failure_and_account_locked_chain(tmp_path, monkeypatch):
    monkeypatch.setattr("rag.config.settings.audit_log_dir", str(tmp_path))

    audit_events.record_login_failure("alice", request_id="req-1")
    audit_events.record_account_locked("user-1", "too many failed login attempts", request_id="req-1")

    log = AuditLog(log_dir=str(tmp_path))
    assert log.count() == 2
    valid, count, error = log.verify_chain()
    assert valid is True
    assert count == 2


def test_record_admin_change_captures_prev_and_new_value(tmp_path, monkeypatch):
    monkeypatch.setattr("rag.config.settings.audit_log_dir", str(tmp_path))

    audit_events.record_admin_change(
        "admin-1", "user_locked", "user:user-1",
        prev_value={"is_active": True}, new_value={"is_active": False}, request_id="req-2",
    )

    log = AuditLog(log_dir=str(tmp_path))
    valid, count, error = log.verify_chain()
    assert valid is True
    assert count == 1
