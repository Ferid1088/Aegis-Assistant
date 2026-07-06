"""Requires a running Docker daemon: `install.run_install()` itself brings up
Postgres/Redis/Neo4j/worker via `docker compose up -d` and runs real Alembic +
store migrations against them.
Run with: uv run pytest tests/integration/test_install_flow.py -v -s
"""
import subprocess

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from rag.bootstrap.env_writer import write_missing_env_vars
from rag.bootstrap.first_admin import ADMIN_PERMISSIONS
from rag.config import settings
from rag.storage.sql import models  # noqa: F401
from rag.storage.sql.models import Role, RolePermission, User, UserRole


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _reset_schema(engine) -> None:
    """Drops every table, however it was created.

    `Base.metadata.drop_all()` only drops tables declared through the ORM's
    Base -- it leaves behind both Alembic's own `alembic_version` tracking table
    and any table an Alembic migration created directly via raw `op.create_table`
    (e.g. `store_schema_versions`), since neither is part of Base.metadata. Left
    behind, either one makes a subsequent `alembic upgrade head` fail: an
    up-to-date `alembic_version` makes it no-op entirely, and a survived
    `store_schema_versions` makes migration 0004 fail with "already exists" even
    when it does run. Dropping and recreating the whole `public` schema (the same
    "clean target before replay" idiom restore.py already uses for exactly this
    reason) is the only way to actually reproduce "a genuinely empty database".
    """
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_install_creates_admin_and_is_idempotent(tmp_path, monkeypatch):
    import install

    # install.py's write_missing_env_vars call uses a bare Path(".env"), which
    # resolves relative to the current working directory. We must NOT chdir the
    # whole process to isolate that write: install.run_install() also shells out
    # to `docker compose`, which resolves docker-compose.yml relative to cwd --
    # chdir-ing the process would break docker compose's ability to find the
    # real repo's compose file. Instead, redirect only the .env write itself to
    # tmp_path, leaving the real working directory (and thus docker compose)
    # alone.
    env_path = tmp_path / ".env"
    monkeypatch.setattr(
        install,
        "write_missing_env_vars",
        lambda _path, values: write_missing_env_vars(env_path, values),
    )

    engine = create_engine(settings.database_url)
    _reset_schema(engine)

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
        _reset_schema(engine)
        engine.dispose()
