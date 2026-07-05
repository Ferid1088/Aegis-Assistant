"""Requires a running Docker daemon: `install.run_install()` itself brings up
Postgres/Redis/Neo4j/worker via `docker compose up -d` and runs real Alembic +
store migrations against them.
Run with: uv run pytest tests/integration/test_install_flow.py -v -s
"""
import subprocess

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from rag.bootstrap.first_admin import ADMIN_PERMISSIONS
from rag.config import settings
from rag.storage.sql import models  # noqa: F401
from rag.storage.sql.base import Base
from rag.storage.sql.models import Role, RolePermission, User, UserRole


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_install_creates_admin_and_is_idempotent(tmp_path, monkeypatch):
    import install

    monkeypatch.chdir(tmp_path)
    # install.py's write_missing_env_vars call uses a bare Path(".env"), which
    # resolves relative to the current working directory -- monkeypatch.chdir
    # above makes that land in tmp_path instead of the real repo's .env.
    env_path = tmp_path / ".env"

    engine = create_engine(settings.database_url)
    Base.metadata.drop_all(engine)

    try:
        install.run_install()

        # -- secrets were written, to tmp_path's .env, not the real repo's --
        assert env_path.exists()
        env_contents = env_path.read_text()
        assert "JWT_SECRET_KEY=" in env_contents
        assert "KEYSTORE_MASTER_KEY=" in env_contents
        assert "POSTGRES_PASSWORD=" in env_contents
        assert "NEO4J_PASSWORD=" in env_contents

        # -- migrations applied: install.run_install()'s own `alembic upgrade head`
        # step is what creates the schema against this genuinely empty database
        # (dropped above); a real admin row below proves the schema it created
        # is usable end-to-end.

        session = sessionmaker(bind=engine)()
        try:
            users_first = session.execute(select(User)).scalars().all()
            assert len(users_first) == 1
            admin = users_first[0]
            assert admin.username == "admin"

            # -- real admin has the full permission set, via a real role/grant --
            roles = session.execute(
                select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == admin.id)
            ).scalars().all()
            assert len(roles) == 1
            granted_permissions = set(
                session.execute(
                    select(RolePermission.permission).where(RolePermission.role_id == roles[0].id)
                ).scalars().all()
            )
            assert granted_permissions == set(ADMIN_PERMISSIONS)
        finally:
            session.close()

        env_contents_after_first_run = env_path.read_text()

        install.run_install()  # second run must be a genuine no-op for secrets + admin

        # -- secrets untouched on second run (no regeneration) --
        assert env_path.read_text() == env_contents_after_first_run

        session = sessionmaker(bind=engine)()
        try:
            users_second = session.execute(select(User)).scalars().all()
            assert len(users_second) == 1
            assert users_second[0].username == "admin"
        finally:
            session.close()
    finally:
        # Leave the shared Postgres database empty so other tests/tasks that reuse
        # it are not tripped up by a stray admin user from this run.
        Base.metadata.drop_all(engine)
        engine.dispose()
