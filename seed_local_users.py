"""Seeds the three fixed local-dev accounts used for a no-Docker laptop setup.

Idempotent: if any of the three usernames already exists, nothing is created
or modified. Can be run standalone (`uv run python seed_local_users.py`)
against an already-migrated database, or is called by install_local.py.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.bootstrap.first_admin import ADMIN_PERMISSIONS
from rag.crosscutting.security.password import hash_password
from rag.infra.stores.sql.base import SessionLocal
from rag.infra.stores.sql.models import Role, RolePermission, User, UserRole

# (username, password, role_name)
LOCAL_USERS = [
    ("admin", "admin12345678", "admin"),
    ("User_1", "User_112345678", "user"),
    ("User_2", "User_212345678", "user"),
]


def _get_or_create_role(db: Session, name: str, permissions: list[str]) -> Role:
    role = db.execute(select(Role).where(Role.name == name)).scalar_one_or_none()
    if role is not None:
        return role
    role = Role(name=name)
    db.add(role)
    db.flush()
    for permission in permissions:
        db.add(RolePermission(role_id=role.id, permission=permission))
    return role


def seed_local_users(db: Session) -> bool:
    """Returns True if any account was created, False if all three already existed."""
    if any(
        db.execute(select(User).where(User.username == username)).scalar_one_or_none() is not None
        for username, _, _ in LOCAL_USERS
    ):
        return False

    admin_role = _get_or_create_role(db, "admin", ADMIN_PERMISSIONS)
    user_role = _get_or_create_role(db, "user", [])
    roles_by_name = {"admin": admin_role, "user": user_role}

    for username, password, role_name in LOCAL_USERS:
        user = User(username=username, password_hash=hash_password(password))
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=roles_by_name[role_name].id))

    db.commit()
    return True


if __name__ == "__main__":
    session = SessionLocal()
    try:
        created = seed_local_users(session)
    finally:
        session.close()

    if created:
        print("Created accounts:")
        for username, password, role in LOCAL_USERS:
            print(f"  username: {username:<10} password: {password:<20} role: {role}")
    else:
        print("Local accounts already exist, skipping.")
