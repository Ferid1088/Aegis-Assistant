from pathlib import Path


def prune_old_backups(backup_dir: Path, keep_count: int) -> list[Path]:
    backups = sorted(
        Path(backup_dir).glob("appliance-backup-*.tar.enc"),
        key=lambda p: p.stat().st_mtime,
    )
    to_delete = backups[: max(0, len(backups) - keep_count)]
    for path in to_delete:
        path.unlink()
    return to_delete
