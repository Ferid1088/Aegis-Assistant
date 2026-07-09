from sqlalchemy import select

from rag.bootstrap.first_admin import ADMIN_PERMISSIONS, ensure_first_admin
from rag.crosscutting.security.password import verify_password
from rag.infra.stores.sql.models import Role, RolePermission, User, UserRole


def test_ensure_first_admin_creates_admin_on_clean_db(db_session):
    result = ensure_first_admin(db_session)

    assert result is not None
    username, password = result
    user = db_session.execute(select(User).where(User.username == username)).scalar_one()
    assert verify_password(password, user.password_hash) is True

    role_ids = [
        r.role_id for r in db_session.execute(select(UserRole).where(UserRole.user_id == user.id)).scalars().all()
    ]
    assert len(role_ids) == 1
    granted_permissions = set(
        db_session.execute(
            select(RolePermission.permission).where(RolePermission.role_id == role_ids[0])
        ).scalars().all()
    )
    assert granted_permissions == set(ADMIN_PERMISSIONS)


def test_ensure_first_admin_is_idempotent(db_session):
    first = ensure_first_admin(db_session)
    assert first is not None

    second = ensure_first_admin(db_session)
    assert second is None

    all_users = db_session.execute(select(User)).scalars().all()
    assert len(all_users) == 1


def test_ensure_first_admin_picks_a_different_username_if_admin_is_taken_by_non_admin(db_session):
    non_admin = User(username="admin")
    db_session.add(non_admin)
    db_session.commit()

    result = ensure_first_admin(db_session)

    assert result is not None
    username, _ = result
    assert username != "admin"
    assert username.startswith("admin-")
