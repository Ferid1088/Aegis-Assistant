import time

from rag.backup.retention import prune_old_backups


def _touch(path, age_seconds_ago=0):
    path.write_text("x")
    if age_seconds_ago:
        mtime = time.time() - age_seconds_ago
        import os
        os.utime(path, (mtime, mtime))


def test_prune_keeps_only_the_n_most_recent(tmp_path):
    for i in range(10):
        _touch(tmp_path / f"appliance-backup-{i:02d}.tar.enc", age_seconds_ago=(10 - i) * 60)

    deleted = prune_old_backups(tmp_path, keep_count=3)

    remaining = sorted(p.name for p in tmp_path.glob("appliance-backup-*.tar.enc"))
    assert len(remaining) == 3
    assert remaining == ["appliance-backup-07.tar.enc", "appliance-backup-08.tar.enc", "appliance-backup-09.tar.enc"]
    assert len(deleted) == 7


def test_prune_ignores_non_matching_files(tmp_path):
    _touch(tmp_path / "appliance-backup-01.tar.enc")
    _touch(tmp_path / "some-other-file.txt")

    prune_old_backups(tmp_path, keep_count=0)

    assert (tmp_path / "some-other-file.txt").exists()
    assert not (tmp_path / "appliance-backup-01.tar.enc").exists()


def test_prune_no_op_when_under_the_limit(tmp_path):
    _touch(tmp_path / "appliance-backup-01.tar.enc")

    deleted = prune_old_backups(tmp_path, keep_count=7)

    assert deleted == []
    assert (tmp_path / "appliance-backup-01.tar.enc").exists()
