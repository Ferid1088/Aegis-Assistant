import shutil
import subprocess
from pathlib import Path

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


def backup_sqlite_file(src_path: Path, dest_path: Path) -> None:
    subprocess.run(["sqlite3", str(src_path), f".backup {dest_path}"], check=True)


def copy_audit_log(dest_dir: Path) -> None:
    shutil.copytree(Path(settings.audit_log_dir), dest_dir, dirs_exist_ok=True)
