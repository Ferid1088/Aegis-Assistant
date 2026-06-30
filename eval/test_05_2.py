"""Tests for 05.2 — authorize(), conversation state machine, hash-chained audit.

Run: PYTHONPATH=. uv run python eval/test_05_2.py
"""

import os
import shutil
import tempfile

from rag.config import settings
from rag.crosscutting.security.audit import AuditEntry, AuditLog
from rag.crosscutting.security.authorize import AuthResource, AuthResult, AuthSubject, authorize
from rag.domain.conversation import (
    Conversation,
    ConversationState,
    can_transition,
    resolve_erasure,
    transition,
)

_original_enforce = settings.acl_enforce


# ── Authorization tests ──────────────────────────────────────────────────

def test_authorize_all_pass():
    settings.acl_enforce = True
    s = AuthSubject(user_id="u1", tenant_id="t1", permissions=["search"],
                    effective_levels=["HR_level_1"])
    r = AuthResource(resource_id="r1", tenant_id="t1", acl_levels=["HR_level_1"],
                     owner_id="u1")
    result = authorize(s, r, "search")
    assert result.allowed, f"Should allow: {result.reason}"
    print("  ✅ authorize: all dimensions pass → ALLOW")


def test_authorize_tenant_deny():
    settings.acl_enforce = True
    s = AuthSubject(user_id="u1", tenant_id="t1", permissions=["search"],
                    effective_levels=["HR_level_1"])
    r = AuthResource(resource_id="r1", tenant_id="t2", acl_levels=["HR_level_1"])
    result = authorize(s, r, "search")
    assert not result.allowed and result.denied_at == "tenant"
    print("  ✅ authorize: cross-tenant → DENY at tenant check")


def test_authorize_explicit_deny_overrides():
    settings.acl_enforce = True
    s = AuthSubject(user_id="u1", tenant_id="t1", permissions=["search"],
                    effective_levels=["HR_level_1"], deny_rules=["search"])
    r = AuthResource(resource_id="r1", tenant_id="t1", acl_levels=["HR_level_1"])
    result = authorize(s, r, "search")
    assert not result.allowed and result.denied_at == "deny_rule"
    print("  ✅ authorize: explicit DENY overrides role ALLOW")


def test_authorize_clearance_deny():
    settings.acl_enforce = True
    s = AuthSubject(user_id="u1", tenant_id="t1", permissions=["search"],
                    effective_levels=["HR_level_1"])
    r = AuthResource(resource_id="r1", tenant_id="t1", acl_levels=["Legal"])
    result = authorize(s, r, "search")
    assert not result.allowed and result.denied_at == "clearance"
    print("  ✅ authorize: insufficient clearance → DENY (INV-2 any-of)")


def test_authorize_empty_acl_deny():
    """INV-1: empty acl_levels = default deny."""
    settings.acl_enforce = True
    s = AuthSubject(user_id="u1", tenant_id="t1", permissions=["search"],
                    effective_levels=["HR_level_1"])
    r = AuthResource(resource_id="r1", tenant_id="t1", acl_levels=[])
    result = authorize(s, r, "search")
    assert not result.allowed and result.denied_at == "clearance"
    assert "INV-1" in result.reason
    print("  ✅ authorize: empty acl_levels → DENY (INV-1 default deny)")


def test_authorize_state_locked():
    settings.acl_enforce = True
    s = AuthSubject(user_id="u1", tenant_id="t1", permissions=["modify"],
                    effective_levels=["HR_level_1"])
    r = AuthResource(resource_id="r1", tenant_id="t1", acl_levels=["HR_level_1"],
                     state="locked", owner_id="u1")
    result = authorize(s, r, "modify")
    assert not result.allowed and result.denied_at == "state"
    print("  ✅ authorize: locked state blocks modify")


def test_authorize_ownership_deny():
    settings.acl_enforce = True
    s = AuthSubject(user_id="u1", tenant_id="t1", permissions=["read"],
                    effective_levels=["HR_level_1"])
    r = AuthResource(resource_id="r1", tenant_id="t1", acl_levels=["HR_level_1"],
                     owner_id="u2")
    result = authorize(s, r, "read")
    assert not result.allowed and result.denied_at == "ownership"
    print("  ✅ authorize: not owner and no grant → DENY")


def test_authorize_break_glass():
    settings.acl_enforce = True
    s = AuthSubject(user_id="admin", tenant_id="system", permissions=["read"],
                    effective_levels=["admin"], is_break_glass=True)
    r = AuthResource(resource_id="r1", tenant_id="t1", acl_levels=["admin"])
    result = authorize(s, r, "read")
    assert result.allowed
    print("  ✅ authorize: break-glass bypasses tenant check")


def test_authorize_unenforced():
    settings.acl_enforce = False
    s = AuthSubject(user_id="u1", tenant_id="t1")
    r = AuthResource(resource_id="r1", tenant_id="t2", acl_levels=[])
    result = authorize(s, r, "anything")
    assert result.allowed
    print("  ✅ authorize: unenforced → always ALLOW")


# ── Conversation state machine tests ─────────────────────────────────────

def test_valid_transitions():
    assert can_transition(ConversationState.ACTIVE, ConversationState.ARCHIVED)
    assert can_transition(ConversationState.ACTIVE, ConversationState.LOCKED)
    assert can_transition(ConversationState.ACTIVE, ConversationState.SOFT_DELETED)
    assert can_transition(ConversationState.SOFT_DELETED, ConversationState.PURGED)
    assert not can_transition(ConversationState.PURGED, ConversationState.ACTIVE)
    assert not can_transition(ConversationState.LOCKED, ConversationState.PURGED)
    print("  ✅ conversation: valid/invalid transitions correct")


def test_legal_hold_blocks_purge():
    c = Conversation(conversation_id="c1", legal_hold=True, state=ConversationState.SOFT_DELETED)
    ok, reason = transition(c, ConversationState.PURGED)
    assert not ok and "legal hold" in reason
    print("  ✅ conversation: legal hold blocks purge (Art. 17(3)(e))")


def test_erasure_precedence():
    c_hold = Conversation(conversation_id="c1", legal_hold=True, erasure_requested=True)
    action, _ = resolve_erasure(c_hold)
    assert action == "refuse", "legal hold should override erasure"

    c_erase = Conversation(conversation_id="c2", erasure_requested=True)
    action, _ = resolve_erasure(c_erase)
    assert action == "purge", "erasure should force purge"

    c_retain = Conversation(conversation_id="c3", retention_days=90)
    action, _ = resolve_erasure(c_retain)
    assert action == "retain"

    c_soft = Conversation(conversation_id="c4", state=ConversationState.SOFT_DELETED)
    action, _ = resolve_erasure(c_soft)
    assert action == "keep_soft_deleted"
    print("  ✅ conversation: erasure precedence (hold > erase > retain > soft-delete)")


# ── Hash-chained audit tests ─────────────────────────────────────────────

def test_audit_chain_integrity():
    tmpdir = tempfile.mkdtemp()
    try:
        log = AuditLog(log_dir=tmpdir)
        log.append(AuditEntry(actor_user="u1", action="login", resource="system", tenant_id="t1"))
        log.append(AuditEntry(actor_user="u1", action="search", resource="doc1", tenant_id="t1"))
        log.append(AuditEntry(actor_user="admin", action="break_glass", resource="doc2",
                              tenant_id="t1", metadata={"justification": "legal request"}))

        valid, count, err = log.verify_chain()
        assert valid and count == 3, f"Chain should be valid with 3 entries: {err}"
        print("  ✅ audit: chain integrity verified (3 entries, no tampering)")
    finally:
        shutil.rmtree(tmpdir)


def test_audit_tamper_detection():
    tmpdir = tempfile.mkdtemp()
    try:
        log = AuditLog(log_dir=tmpdir)
        log.append(AuditEntry(actor_user="u1", action="login", resource="system"))
        log.append(AuditEntry(actor_user="u1", action="search", resource="doc1"))

        # Tamper: modify line 1
        import json
        path = os.path.join(tmpdir, "immutable_audit.jsonl")
        with open(path) as f:
            lines = f.readlines()
        entry = json.loads(lines[0])
        entry["action"] = "TAMPERED"
        lines[0] = json.dumps(entry) + "\n"
        with open(path, "w") as f:
            f.writelines(lines)

        log2 = AuditLog(log_dir=tmpdir)
        valid, count, err = log2.verify_chain()
        assert not valid, "Tampered chain should be detected"
        assert "mismatch" in err
        print("  ✅ audit: tamper detection works (modified entry breaks chain)")
    finally:
        shutil.rmtree(tmpdir)


def test_audit_delete_detection():
    tmpdir = tempfile.mkdtemp()
    try:
        log = AuditLog(log_dir=tmpdir)
        log.append(AuditEntry(actor_user="u1", action="a1", resource="r1"))
        log.append(AuditEntry(actor_user="u1", action="a2", resource="r2"))
        log.append(AuditEntry(actor_user="u1", action="a3", resource="r3"))

        # Delete middle entry
        path = os.path.join(tmpdir, "immutable_audit.jsonl")
        with open(path) as f:
            lines = f.readlines()
        with open(path, "w") as f:
            f.write(lines[0])
            f.write(lines[2])  # skip line 1

        log2 = AuditLog(log_dir=tmpdir)
        valid, _, err = log2.verify_chain()
        assert not valid, "Deleted entry should break chain"
        print("  ✅ audit: deletion detection works (removed entry breaks chain)")
    finally:
        shutil.rmtree(tmpdir)


def main():
    print("=== 05.2 Tests: Authorization + Conversation + Audit ===\n")
    tests = [
        test_authorize_all_pass,
        test_authorize_tenant_deny,
        test_authorize_explicit_deny_overrides,
        test_authorize_clearance_deny,
        test_authorize_empty_acl_deny,
        test_authorize_state_locked,
        test_authorize_ownership_deny,
        test_authorize_break_glass,
        test_authorize_unenforced,
        test_valid_transitions,
        test_legal_hold_blocks_purge,
        test_erasure_precedence,
        test_audit_chain_integrity,
        test_audit_tamper_detection,
        test_audit_delete_detection,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"  ❌ {t.__name__}: {type(e).__name__}: {e}")
        finally:
            settings.acl_enforce = _original_enforce

    print(f"\n{'='*50}")
    print(f"  {passed}/{len(tests)} tests passed")
    if passed == len(tests):
        print("  🎉 All 05.2 invariants verified")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
