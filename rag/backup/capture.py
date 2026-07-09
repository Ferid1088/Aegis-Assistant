import shutil
import subprocess
from pathlib import Path

from rag.bootstrap.wait_for_neo4j import wait_for_neo4j_ready
from rag.bootstrap.wait_for_qdrant import wait_for_qdrant_ready
from rag.config import settings


def dump_postgres(dest_path: Path) -> None:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-U", "postgres", "appliance"],
        capture_output=True, check=True,
    )
    Path(dest_path).write_bytes(result.stdout)


def copy_qdrant(dest_dir: Path) -> None:
    # Server mode (settings.qdrant_url set) means a persistent, continuously-writing
    # `qdrant` container may hold these files (segments, WAL) open -- copying them
    # live risks a torn/corrupt snapshot. Stop/copy/restart, mirroring dump_neo4j
    # below exactly. Embedded mode (qdrant_url empty) has no separate server
    # process holding data/qdrant open -- nothing to stop, so keep the old plain
    # copytree for installs still on that mode.
    if settings.qdrant_url:
        subprocess.run(["docker", "compose", "stop", "qdrant"], check=True)
        try:
            shutil.copytree(Path(settings.qdrant_path), dest_dir, dirs_exist_ok=True)
        finally:
            subprocess.run(["docker", "compose", "start", "qdrant"], check=True)
            # `start` returns once the container process launches, not once Qdrant
            # actually accepts REST requests again -- anything that touches Qdrant
            # right after this function returns would otherwise race that boot time.
            wait_for_qdrant_ready()
    else:
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
