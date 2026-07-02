from sqlalchemy import create_engine, inspect

from rag.storage.sql.base import Base
from rag.storage.sql import models  # noqa: F401  (registers models on Base.metadata)

EXPECTED_TABLES = {
    "departments", "access_levels", "roles", "role_access_grants",
    "role_permissions", "user_roles", "document_types", "users",
    "sso_identities", "sessions", "refresh_tokens", "login_attempts",
    "conversations", "conversation_grants",
}


def test_all_expected_tables_are_registered():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    actual = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES <= actual


def test_insert_and_query_department_role_user(db_session):
    from rag.storage.sql.models import AccessLevel, Department, Role, RoleAccessGrant, User, UserRole

    dept = Department(name="HR")
    role = Role(name="hr_analyst")
    db_session.add_all([dept, role])
    db_session.flush()

    level = AccessLevel(department_id=dept.id, label="HR_L1", rank=1)
    db_session.add(level)
    db_session.flush()

    db_session.add(RoleAccessGrant(role_id=role.id, access_level_id=level.id))

    user = User(username="alice", department_id=dept.id)
    db_session.add(user)
    db_session.flush()

    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()

    fetched = db_session.query(User).filter_by(username="alice").one()
    assert fetched.department_id == dept.id


def test_insert_conversation_and_grant(db_session):
    from rag.storage.sql.models import Conversation, ConversationGrant, User

    owner = User(username="alice")
    db_session.add(owner)
    db_session.flush()

    conv = Conversation(owner_id=owner.id, state="active")
    db_session.add(conv)
    db_session.flush()

    grantee = User(username="bob")
    db_session.add(grantee)
    db_session.flush()
    db_session.add(ConversationGrant(conversation_id=conv.id, user_id=grantee.id, permission="read"))
    db_session.commit()

    fetched = db_session.query(Conversation).filter_by(owner_id=owner.id).one()
    assert fetched.state == "active"
    assert fetched.legal_hold is False
    assert fetched.erasure_requested is False
