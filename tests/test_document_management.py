import os
import tempfile

from rag.capabilities.document_management import MANAGE_VERSIONS, authorize_version_action
from rag.config import settings
from rag.crosscutting.security.audit import AuditLog
from rag.crosscutting.security.authorize import AuthResource, AuthSubject

_original_enforce = settings.acl_enforce


def _audit_log():
    tmpdir = tempfile.mkdtemp()
    return AuditLog(log_dir=tmpdir), tmpdir


def test_manage_versions_allowed_for_permitted_user():
    settings.acl_enforce = True
    try:
        log, tmpdir = _audit_log()
        subject = AuthSubject(
            user_id="admin1", tenant_id="t1", permissions=[MANAGE_VERSIONS],
            effective_levels=["L1"],
        )
        resource = AuthResource(resource_id="L1", tenant_id="t1", acl_levels=["L1"])
        result = authorize_version_action(subject, resource, MANAGE_VERSIONS, log, version_id="v2")
        assert result.allowed
        assert log.count() == 1
    finally:
        settings.acl_enforce = _original_enforce


def test_manage_versions_denied_for_plain_upload_permission():
    settings.acl_enforce = True
    try:
        log, tmpdir = _audit_log()
        subject = AuthSubject(
            user_id="user1", tenant_id="t1", permissions=["upload"],  # no manage_versions
            effective_levels=["L1"],
        )
        resource = AuthResource(resource_id="L1", tenant_id="t1", acl_levels=["L1"])
        result = authorize_version_action(subject, resource, MANAGE_VERSIONS, log, version_id="v2")
        assert not result.allowed
        assert result.denied_at == "role"
    finally:
        settings.acl_enforce = _original_enforce


def test_every_attempt_is_audited_including_denials():
    settings.acl_enforce = True
    try:
        log, tmpdir = _audit_log()
        subject = AuthSubject(user_id="user1", tenant_id="t1", permissions=[], effective_levels=[])
        resource = AuthResource(resource_id="L1", tenant_id="t1", acl_levels=["L1"])

        authorize_version_action(subject, resource, MANAGE_VERSIONS, log, version_id="v2")
        valid, count, err = log.verify_chain()
        assert valid, err
        assert count == 1
    finally:
        settings.acl_enforce = _original_enforce
