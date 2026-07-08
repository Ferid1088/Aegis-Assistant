"""Requires a running Postgres + Neo4j: `docker compose up -d postgres neo4j` before
running. Also requires the `sqlite3` CLI on the host (used by backup_sqlite_file).
Run with: uv run pytest tests/integration/test_backup_restore_flow.py -v -s

This test proves the REAL, unmocked backup.run_backup() -> restore.run_restore()
round-trip: it writes real rows to Postgres and a real point into the embedded
Qdrant directory at settings.qdrant_path, backs them up, mutates/deletes them, then
restores and asserts the originals are back.

Because run_backup/run_restore operate on hardcoded appliance paths (data/qdrant,
data/documents.db, data/observability.db, data/audit -- not tmp_path), this test
snapshots whatever is already at those paths before it runs and puts it back
afterward, so it doesn't leave the worktree's data/ directory in a state that
breaks other work.
"""
import shutil
import subprocess
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models as qm
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from rag.config import settings
from rag.infra.stores.sql import models  # noqa: F401
from rag.infra.stores.sql.base import Base
from rag.infra.stores.sql.models import User


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _sqlite3_available() -> bool:
    return shutil.which("sqlite3") is not None


SKIP_REASON = "docker compose / sqlite3 CLI not available locally"


@pytest.fixture()
def preserve_data_dir():
    """Snapshot the real appliance data/ paths that run_restore will overwrite, and
    restore them afterward -- run_restore is destructive by design (it writes to
    hardcoded paths, not tmp_path), so this test must clean up after itself.
    """
    paths = [
        Path("data/qdrant"),
        Path("data/neo4j"),
        Path("data/documents.db"),
        Path("data/observability.db"),
        Path("data/audit"),
        Path("data/progression_rules.json"),
    ]
    snapshot_root = Path(".data_snapshot_backup_restore_test")
    shutil.rmtree(snapshot_root, ignore_errors=True)
    snapshot_root.mkdir(parents=True)

    saved = {}
    for p in paths:
        if p.exists():
            dest = snapshot_root / p.name
            if p.is_dir():
                shutil.copytree(p, dest)
            else:
                shutil.copy2(p, dest)
            saved[p] = dest

    # The test creates its own "documents" collection at settings.qdrant_path from
    # scratch -- on an appliance that's already been through install.py (which
    # creates that same collection via the qdrant baseline migration), it would
    # already exist here. Clear it now that it's snapshotted, so the test starts
    # from the pristine state it actually assumes.
    if Path("data/qdrant").exists():
        shutil.rmtree("data/qdrant")

    try:
        yield
    finally:
        for p in paths:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()

        for p, dest in saved.items():
            if dest.is_dir():
                shutil.copytree(dest, p)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, p)

        shutil.rmtree(snapshot_root, ignore_errors=True)


@pytest.mark.skipif(
    not (_docker_available() and _sqlite3_available()), reason=SKIP_REASON
)
def test_backup_then_restore_preserves_known_data(tmp_path, preserve_data_dir):
    import backup
    import restore

    engine = create_engine(settings.database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    marker_user = User(username="backup-restore-marker-user")
    session.add(marker_user)
    session.commit()
    marker_id = marker_user.id

    # Seed a real point into the real embedded Qdrant directory at
    # settings.qdrant_path, so the test also proves the Qdrant capture/restore
    # path (not just Postgres). The client must be closed before backup/restore
    # touch the directory, since embedded Qdrant holds an exclusive file lock --
    # closed in a finally so a failed assertion doesn't leave that lock held for
    # the rest of the pytest session (which would hang any later test that also
    # needs an embedded Qdrant client at this same path).
    qdrant_dir = Path(settings.qdrant_path)
    qdrant_dir.parent.mkdir(parents=True, exist_ok=True)
    qc = QdrantClient(path=str(qdrant_dir))
    try:
        qc.create_collection(
            settings.qdrant_collection,
            vectors_config={"dense": qm.VectorParams(size=4, distance=qm.Distance.COSINE)},
            sparse_vectors_config={"sparse": qm.SparseVectorParams()},
        )
        qc.upsert(
            settings.qdrant_collection,
            points=[
                qm.PointStruct(
                    id=1,
                    vector={
                        "dense": [0.1, 0.2, 0.3, 0.4],
                        "sparse": qm.SparseVector(indices=[0], values=[1.0]),
                    },
                    payload={"marker": "qdrant-restore-marker"},
                )
            ],
        )
    finally:
        qc.close()

    try:
        backup_dir = tmp_path / "backups"
        output_path = backup.run_backup(backup_dir=backup_dir)
        assert output_path.exists()

        # Mutate Postgres row
        session.execute(
            select(User).where(User.id == marker_id)
        ).scalar_one().username = "mutated"
        session.commit()

        # Mutate/delete the Qdrant point
        qc2 = QdrantClient(path=str(qdrant_dir))
        try:
            qc2.delete(
                settings.qdrant_collection,
                points_selector=qm.PointIdsList(points=[1]),
            )
        finally:
            qc2.close()

        restore.run_restore(output_path)

        fresh_session = sessionmaker(bind=engine)()
        try:
            restored_user = fresh_session.execute(
                select(User).where(User.id == marker_id)
            ).scalar_one()
            assert restored_user.username == "backup-restore-marker-user"

            qc3 = QdrantClient(path=str(qdrant_dir))
            try:
                restored_point = qc3.retrieve(settings.qdrant_collection, ids=[1])
                assert len(restored_point) == 1
                assert restored_point[0].payload["marker"] == "qdrant-restore-marker"
            finally:
                qc3.close()
        finally:
            fresh_session.close()
    finally:
        session.close()
        engine.dispose()
