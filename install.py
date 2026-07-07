"""Installer: takes a fresh Docker-equipped machine to a running, migrated appliance
with a first admin account. Every step is idempotent -- re-running this script never
regenerates an existing secret, never creates a second admin, and never fails merely
because a prior run already completed that step.
"""

import subprocess
from pathlib import Path

from rag.bootstrap.env_writer import read_env_value, write_missing_env_vars
from rag.bootstrap.first_admin import ensure_first_admin
from rag.bootstrap.glitchtip_db import ensure_glitchtip_database
from rag.bootstrap.prereqs import check_docker, check_gpu, check_ram
from rag.bootstrap.secrets_gen import (
    generate_glitchtip_secret_key, generate_grafana_admin_password, generate_jwt_secret, generate_keystore_master_key,
    generate_neo4j_password, generate_postgres_password,
)
from rag.bootstrap.tls_cert import ensure_tls_certificate
from rag.bootstrap.wait_for_postgres import wait_for_postgres_ready
from rag.config import settings
from rag.healthcheck import main as healthcheck_main
from rag.storage.sql.base import SessionLocal, reset_engine

import run_store_migrate


def run_install() -> None:
    print("== Checking prerequisites ==")
    check_docker()
    check_ram()
    check_gpu()

    print("== Generating TLS certificate ==")
    ensure_tls_certificate()

    print("== Generating secrets ==")
    env_path = Path(".env")
    written = write_missing_env_vars(env_path, {
        "JWT_SECRET_KEY": generate_jwt_secret(),
        "KEYSTORE_MASTER_KEY": generate_keystore_master_key(),
        # Consumed by docker-compose.yml's postgres/pgbouncer/app/worker services
        # (interpolated via ${POSTGRES_PASSWORD:-password}) and, in-process, by
        # the database_url resync below (Phase 8.10b). Only takes effect against
        # a genuinely fresh Postgres data volume -- Postgres (like Neo4j) applies
        # POSTGRES_PASSWORD only during its first-ever initdb on an empty volume.
        "POSTGRES_PASSWORD": generate_postgres_password(),
        "NEO4J_PASSWORD": generate_neo4j_password(),
        "REDIS_URL": "redis://redis:6379",
        "QDRANT_URL": "http://localhost:6333",
        "GLITCHTIP_SECRET_KEY": generate_glitchtip_secret_key(),
        "GRAFANA_ADMIN_PASSWORD": generate_grafana_admin_password(),
    })
    if written:
        print(f"Generated: {', '.join(written)}")
    else:
        print("All secrets already present, nothing generated.")

    # Sync the in-process settings singleton with whatever NEO4J_PASSWORD actually
    # ended up in .env (freshly generated above, or already present from a prior
    # run) -- `settings` was constructed at module import time, before this run's
    # secrets existed, so without this it would still hold the stale default while
    # the Neo4j container (created fresh from this same .env, next step) uses the
    # real value.
    settings.neo4j_password = read_env_value(env_path, "NEO4J_PASSWORD") or settings.neo4j_password
    # Same class of bug, same fix: `settings` was constructed at import time with
    # qdrant_url=="" (the embedded-mode default) -- on a fresh install, QDRANT_URL
    # doesn't exist in .env until write_missing_env_vars() writes it a few lines
    # above, so without this, run_store_migrate.main() and healthcheck_main() below
    # would silently run against embedded Qdrant (./data/qdrant via QdrantClient(path=...))
    # instead of the real `qdrant` server container this whole sub-phase stands up.
    settings.qdrant_url = read_env_value(env_path, "QDRANT_URL") or settings.qdrant_url
    # Same class of bug as neo4j_password/qdrant_url above, but database_url
    # can't use the same `or` passthrough idiom directly -- POSTGRES_PASSWORD
    # is only the password component, not the full connection string. Rebuild
    # it here so run_store_migrate.main()/first-admin creation/healthcheck_main()
    # below (all later in this same process) use the real generated password
    # instead of the stale import-time dev-default. reset_engine() clears
    # rag/storage/sql/base.py's cached engine so the next SessionLocal() call
    # picks up the rebuilt URL (Phase 8.10b).
    postgres_password = read_env_value(env_path, "POSTGRES_PASSWORD")
    if postgres_password:
        settings.database_url = f"postgresql+psycopg://postgres:{postgres_password}@localhost:5432/appliance"
        reset_engine()

    print("== Starting services ==")
    # Must exist before `docker compose up` touches it: on Linux, dockerd (running
    # as root) auto-creates missing bind-mount host directories -- if `./data`
    # itself doesn't exist yet, it gets created root-owned, and every host-side
    # write under it (SQLite document store, Qdrant, uploads) then fails with
    # "unable to open database file" for the unprivileged user running this
    # script. Creating it first as that user keeps ownership sane; the
    # postgres/neo4j/redis subdirectories Docker still creates underneath it are
    # fine root-owned since no host-side code writes into those directly.
    Path("data").mkdir(exist_ok=True)
    subprocess.run(["docker", "compose", "up", "-d"], check=True)

    # `up -d` returns once containers are started, not once postgres has finished
    # its first-run initdb bootstrap -- wait for it before anything execs into it.
    wait_for_postgres_ready()

    ensure_glitchtip_database()

    print("== Running migrations ==")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    run_store_migrate.main()

    print("== Creating first admin ==")
    db = SessionLocal()
    try:
        result = ensure_first_admin(db)
    finally:
        db.close()

    if result is not None:
        username, password = result
        print("=" * 60)
        print("SAVE THIS NOW -- it will not be shown again:")
        print(f"  username: {username}")
        print(f"  password: {password}")
        print("=" * 60)
    else:
        print("Admin account already exists, skipping.")

    print("== Verifying health ==")
    healthcheck_main()

    print("\n🎉 Install complete.")


if __name__ == "__main__":
    run_install()
