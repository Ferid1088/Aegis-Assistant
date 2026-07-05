"""Restores an appliance backup archive produced by backup.py.

Restore is inherently more invasive than backup: Neo4j is stopped for its file
replacement (same as backup), and Postgres is replayed via psql. Prints a
step-by-step progress log since an operator running this needs visibility into
what's happening at each stage of a "stop everything, replace data, restart"
operation.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from rag.backup.archive import decrypt_archive, extract_tar
from rag.storage.sql.base import SessionLocal


def run_restore(backup_path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        db = SessionLocal()
        try:
            decrypted_tar = tmp_path / "decrypted.tar"
            print(f"Decrypting {backup_path}...")
            decrypt_archive(db, Path(backup_path), decrypted_tar)
        finally:
            db.close()

        extracted_dir = tmp_path / "extracted"
        print("Extracting archive...")
        extract_tar(decrypted_tar, extracted_dir)

        print("Restoring Postgres...")
        # dump_postgres captures a plain-SQL pg_dump (CREATE TABLE + COPY, no
        # --clean/--if-exists). Replaying that directly into a database that
        # already has the same schema/rows (the normal in-place restore case)
        # makes every CREATE TABLE/ADD CONSTRAINT statement fail with "already
        # exists", and COPY rows collide on primary key -- psql doesn't abort on
        # these errors by default, so the restore would appear to succeed while
        # silently leaving the old (pre-restore) data in place. Dropping and
        # recreating the public schema first gives the dump a clean target.
        subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "appliance",
             "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
            check=True,
        )
        with open(extracted_dir / "postgres.dump", "rb") as dump_file:
            subprocess.run(
                ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "appliance"],
                stdin=dump_file, check=True,
            )

        print("Restoring Qdrant...")
        # rmtree the destination first so the restore *replaces* the live
        # directory rather than merging into it -- copytree(dirs_exist_ok=True)
        # would leave files present live but absent from the backup untouched,
        # which for Qdrant/Neo4j can mix newer segment/index files with
        # restored-but-older ones and silently corrupt the store. Same
        # "clean target before replay" principle as the Postgres schema reset.
        shutil.rmtree(Path("data/qdrant"), ignore_errors=True)
        shutil.copytree(extracted_dir / "qdrant", Path("data/qdrant"))

        print("Stopping Neo4j to restore its data...")
        subprocess.run(["docker", "compose", "stop", "neo4j"], check=True)
        try:
            shutil.rmtree(Path("data/neo4j"), ignore_errors=True)
            shutil.copytree(extracted_dir / "neo4j", Path("data/neo4j"))
        finally:
            print("Restarting Neo4j...")
            subprocess.run(["docker", "compose", "start", "neo4j"], check=True)

        print("Restoring SQLite files and audit log...")
        shutil.copy2(extracted_dir / "documents.db", Path("data/documents.db"))
        shutil.copy2(extracted_dir / "observability.db", Path("data/observability.db"))
        shutil.rmtree(Path("data/audit"), ignore_errors=True)
        shutil.copytree(extracted_dir / "audit", Path("data/audit"))

        progression_rules_path = extracted_dir / "progression_rules.json"
        if progression_rules_path.exists():
            shutil.copy2(progression_rules_path, Path("data/progression_rules.json"))

        print("Restore complete.")


def main():
    parser = argparse.ArgumentParser(description="Restore an appliance backup archive")
    parser.add_argument("backup_path", type=Path, help="Path to the .tar.enc backup file")
    args = parser.parse_args()

    if not args.backup_path.exists():
        parser.error(f"File not found: {args.backup_path}")

    run_restore(args.backup_path)


if __name__ == "__main__":
    main()
