import shutil
import subprocess
from pathlib import Path

from rag.bootstrap.wait_for_neo4j import wait_for_neo4j_ready
from rag.config import settings


def dump_postgres(dest_path: Path) -> None:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "postgres", "appliance"],
        capture_output=True, check=True,
    )
    Path(dest_path).write_bytes(result.stdout)


def copy_qdrant(dest_dir: Path) -> None:
    shutil.copytree(Path(settings.qdrant_path), dest_dir, dirs_exist_ok=True)


def dump_neo4j(dest_dir: Path) -> None:
    subprocess.run(["docker", "compose", "stop", "neo4j"], check=True)
    try:
        shutil.copytree(Path("data/neo4j"), dest_dir, dirs_exist_ok=True)
    finally:
        subprocess.run(["docker", "compose", "start", "neo4j"], check=True)
        # `start` returns once the container process launches, not once Neo4j (a
        # JVM app, much slower to boot than Postgres) actually accepts Bolt
        # connections again -- anything that touches Neo4j right after this
        # function returns (e.g. the next test/migration step) would otherwise
        # race that boot time.
        wait_for_neo4j_ready()


def backup_sqlite_file(src_path: Path, dest_path: Path) -> None:
    subprocess.run(["sqlite3", str(src_path), f".backup {dest_path}"], check=True)


def copy_audit_log(dest_dir: Path) -> None:
    """Copies the audit log directory -- which, unlike Qdrant/Neo4j's docker-managed
    bind mounts, doesn't exist until the first audit-worthy event is ever logged
    (see AuditLog.__init__). A fresh appliance backed up before that first event has
    nothing to copy; write an empty destination rather than erroring.
    """
    src = Path(settings.audit_log_dir)
    if src.exists():
        shutil.copytree(src, dest_dir, dirs_exist_ok=True)
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
