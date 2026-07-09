"""Backs up Postgres, Qdrant, Neo4j, SQLite files, and the audit log into one
encrypted, timestamped archive under backups/.

RPO/RTO runbook:
- RPO = however often this script is scheduled to run (phase 8.5's installer wires
  cron; until then, RPO is "however often an operator runs this by hand"). Recommended
  cadence: daily.
- RTO = time to run restore.py end-to-end against a fresh appliance. Dominated by the
  Postgres dump replay and the Neo4j file copy; expected to be single-digit minutes at
  this appliance's target data scale (see phase 8 doc §12.6's sizing tiers). Not
  benchmarked here — the integration test proves correctness, not a timed SLA.

A failing capture step aborts the whole run before any archive is written to
backups/ — a partial/truncated backup is worse than no backup, since it can silently
pass a "backup succeeded" check while missing data.
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from rag.backup.archive import build_tar, encrypt_archive
from rag.backup.capture import (
    backup_sqlite_file, copy_audit_log, copy_qdrant, dump_neo4j, dump_postgres,
)
from rag.backup.retention import prune_old_backups
from rag.config import settings
from rag.infra.stores.sql.base import SessionLocal


def run_backup(backup_dir: Path = Path("backups")) -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        pg_dump_path = tmp_path / "postgres.dump"
        dump_postgres(pg_dump_path)

        qdrant_dir = tmp_path / "qdrant"
        copy_qdrant(qdrant_dir)

        neo4j_dir = tmp_path / "neo4j"
        dump_neo4j(neo4j_dir)

        documents_db_path = tmp_path / "documents.db"
        backup_sqlite_file(Path(settings.sqlite_path), documents_db_path)

        observability_db_path = tmp_path / "observability.db"
        backup_sqlite_file(Path(settings.observability_db_path), observability_db_path)

        audit_dir = tmp_path / "audit"
        copy_audit_log(audit_dir)

        sources = {
            "postgres.dump": pg_dump_path,
            "qdrant": qdrant_dir,
            "neo4j": neo4j_dir,
            "documents.db": documents_db_path,
            "observability.db": observability_db_path,
            "audit": audit_dir,
        }
        progression_rules_path = Path("data/progression_rules.json")
        if progression_rules_path.exists():
            sources["progression_rules.json"] = progression_rules_path

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        plain_tar_path = tmp_path / f"appliance-backup-{timestamp}.tar"
        build_tar(sources, plain_tar_path)

        db = SessionLocal()
        try:
            output_path = backup_dir / f"appliance-backup-{timestamp}.tar.enc"
            encrypt_archive(db, plain_tar_path, output_path)
        finally:
            db.close()

    prune_old_backups(backup_dir, settings.backup_retention_count)
    return output_path


def main():
    output_path = run_backup()
    print(f"Backup written to {output_path}")


if __name__ == "__main__":
    main()
