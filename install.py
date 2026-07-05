"""Installer: takes a fresh Docker-equipped machine to a running, migrated appliance
with a first admin account. Every step is idempotent -- re-running this script never
regenerates an existing secret, never creates a second admin, and never fails merely
because a prior run already completed that step.
"""

import subprocess
from pathlib import Path

from rag.bootstrap.env_writer import write_missing_env_vars
from rag.bootstrap.first_admin import ensure_first_admin
from rag.bootstrap.prereqs import check_docker, check_gpu, check_ram
from rag.bootstrap.secrets_gen import (
    generate_jwt_secret, generate_keystore_master_key, generate_neo4j_password, generate_postgres_password,
)
from rag.healthcheck import main as healthcheck_main
from rag.storage.sql.base import SessionLocal

import run_store_migrate


def run_install() -> None:
    print("== Checking prerequisites ==")
    check_docker()
    check_ram()
    check_gpu()

    print("== Generating secrets ==")
    written = write_missing_env_vars(Path(".env"), {
        "JWT_SECRET_KEY": generate_jwt_secret(),
        "KEYSTORE_MASTER_KEY": generate_keystore_master_key(),
        "POSTGRES_PASSWORD": generate_postgres_password(),
        "NEO4J_PASSWORD": generate_neo4j_password(),
    })
    if written:
        print(f"Generated: {', '.join(written)}")
    else:
        print("All secrets already present, nothing generated.")

    print("== Starting services ==")
    subprocess.run(["docker", "compose", "up", "-d"], check=True)

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
