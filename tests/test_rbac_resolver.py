from rag.crosscutting.security.rbac_resolver import resolve_auth_subject
from rag.infra.stores.sql.models import AccessLevel, Department, Role, RoleAccessGrant, RolePermission, User, UserRole


def _make_user_with_role(db_session, role_name, permissions, level_labels):
    dept = Department(name="HR")
    db_session.add(dept)
    db_session.flush()

    role = Role(name=role_name)
    db_session.add(role)
    db_session.flush()

    for perm in permissions:
        db_session.add(RolePermission(role_id=role.id, permission=perm))

    for label in level_labels:
        level = AccessLevel(department_id=dept.id, label=label, rank=1)
        db_session.add(level)
        db_session.flush()
        db_session.add(RoleAccessGrant(role_id=role.id, access_level_id=level.id))

    user = User(username="alice", department_id=dept.id)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user


def test_resolve_auth_subject_returns_roles_permissions_and_levels(db_session):
    user = _make_user_with_role(db_session, "hr_analyst", ["search", "admin:users"], ["HR_L1", "HR_L2"])

    subject = resolve_auth_subject(db_session, user)

    assert subject.user_id == str(user.id)
    assert subject.tenant_id == "default"
    assert subject.roles == ["hr_analyst"]
    assert set(subject.permissions) == {"search", "admin:users"}
    assert set(subject.effective_levels) == {"HR_L1", "HR_L2"}
    assert subject.deny_rules == []


def test_resolve_auth_subject_with_no_roles_has_empty_grants(db_session):
    user = User(username="bob")
    db_session.add(user)
    db_session.commit()

    subject = resolve_auth_subject(db_session, user)

    assert subject.roles == []
    assert subject.permissions == []
    assert subject.effective_levels == []
