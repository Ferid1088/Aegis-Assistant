import json
import tarfile
from unittest.mock import MagicMock, patch

import pytest


def _make_signed_bundle(tmp_path, version=2, tamper_signature=False, tamper_file=False):
    from generate_signing_keypair import generate_keypair
    from rag.update.bundle_signing import sha256_file, sign_manifest

    keys_dir = tmp_path / "keys"
    private_path, public_path = generate_keypair(keys_dir)

    bundle_dir = tmp_path / "bundle-build"
    bundle_dir.mkdir()
    (bundle_dir / "worker-image.tar").write_bytes(b"worker-bytes")
    (bundle_dir / "app-image.tar").write_bytes(b"app-bytes")

    manifest = {
        "version": version,
        "changelog": "test",
        "files": {
            "worker-image.tar": sha256_file(bundle_dir / "worker-image.tar"),
            "app-image.tar": sha256_file(bundle_dir / "app-image.tar"),
        },
    }
    manifest_bytes = json.dumps(manifest).encode()
    (bundle_dir / "manifest.json").write_bytes(manifest_bytes)

    signature = sign_manifest(manifest_bytes, private_path)
    if tamper_signature:
        signature = bytes([signature[0] ^ 0xFF]) + signature[1:]
    (bundle_dir / "manifest.sig").write_bytes(signature)

    if tamper_file:
        (bundle_dir / "worker-image.tar").write_bytes(b"tampered-bytes")

    bundle_tar_path = tmp_path / f"appliance-update-v{version}.tar"
    with tarfile.open(bundle_tar_path, "w") as tar:
        for item in bundle_dir.iterdir():
            tar.add(item, arcname=item.name)

    return bundle_tar_path, public_path


@patch("update.healthcheck_main")
@patch("update.run_store_migrate")
@patch("update.subprocess.run")
@patch("update.restore")
@patch("update.backup")
def test_run_update_happy_path_calls_steps_in_order(
    mock_backup, mock_restore, mock_subprocess_run, mock_run_store_migrate, mock_healthcheck,
    tmp_path, monkeypatch,
):
    import update
    bundle_path, public_key_path = _make_signed_bundle(tmp_path, version=2)
    monkeypatch.setattr(update, "PUBLIC_KEY_PATH", public_key_path)
    version_path = tmp_path / "appliance_version.json"
    monkeypatch.setattr(update, "read_version_state", lambda: {"version": 1})
    written_state = {}
    monkeypatch.setattr(update, "write_version_state", lambda state: written_state.update(state))
    mock_backup.run_backup.return_value = tmp_path / "backups" / "pre-update.tar.enc"

    update.run_update(bundle_path)

    mock_backup.run_backup.assert_called_once()
    assert mock_subprocess_run.call_count >= 4  # 2x docker load, 2x docker tag, docker compose up -d, alembic upgrade head
    mock_run_store_migrate.main.assert_called_once()
    mock_healthcheck.assert_called_once()
    mock_restore.run_restore.assert_not_called()
    assert written_state["version"] == 2
    assert written_state["previous"]["version"] == 1
    assert written_state["previous"]["backup_path"] == str(mock_backup.run_backup.return_value)


@patch("update.healthcheck_main")
@patch("update.run_store_migrate")
@patch("update.subprocess.run")
@patch("update.restore")
@patch("update.backup")
def test_run_update_restores_backup_when_migration_raises_systemexit(
    mock_backup, mock_restore, mock_subprocess_run, mock_run_store_migrate, mock_healthcheck,
    tmp_path, monkeypatch,
):
    import update
    bundle_path, public_key_path = _make_signed_bundle(tmp_path, version=2)
    monkeypatch.setattr(update, "PUBLIC_KEY_PATH", public_key_path)
    monkeypatch.setattr(update, "read_version_state", lambda: {"version": 1})
    monkeypatch.setattr(update, "write_version_state", lambda state: None)
    mock_backup.run_backup.return_value = tmp_path / "backups" / "pre-update.tar.enc"
    mock_run_store_migrate.main.side_effect = SystemExit(1)

    with pytest.raises(SystemExit):
        update.run_update(bundle_path)

    mock_restore.run_restore.assert_called_once_with(mock_backup.run_backup.return_value)
    mock_healthcheck.assert_not_called()


@patch("update.healthcheck_main")
@patch("update.run_store_migrate")
@patch("update.subprocess.run")
@patch("update.restore")
@patch("update.backup")
def test_run_update_rejects_tampered_signature_before_backing_up(
    mock_backup, mock_restore, mock_subprocess_run, mock_run_store_migrate, mock_healthcheck,
    tmp_path, monkeypatch,
):
    import update
    bundle_path, public_key_path = _make_signed_bundle(tmp_path, version=2, tamper_signature=True)
    monkeypatch.setattr(update, "PUBLIC_KEY_PATH", public_key_path)
    monkeypatch.setattr(update, "read_version_state", lambda: {"version": 1})

    with pytest.raises(RuntimeError, match="signature"):
        update.run_update(bundle_path)

    mock_backup.run_backup.assert_not_called()


@patch("update.healthcheck_main")
@patch("update.run_store_migrate")
@patch("update.subprocess.run")
@patch("update.restore")
@patch("update.backup")
def test_run_update_rejects_tampered_file_before_backing_up(
    mock_backup, mock_restore, mock_subprocess_run, mock_run_store_migrate, mock_healthcheck,
    tmp_path, monkeypatch,
):
    import update
    bundle_path, public_key_path = _make_signed_bundle(tmp_path, version=2, tamper_file=True)
    monkeypatch.setattr(update, "PUBLIC_KEY_PATH", public_key_path)
    monkeypatch.setattr(update, "read_version_state", lambda: {"version": 1})

    with pytest.raises(RuntimeError, match="integrity"):
        update.run_update(bundle_path)

    mock_backup.run_backup.assert_not_called()


@patch("update.healthcheck_main")
@patch("update.run_store_migrate")
@patch("update.subprocess.run")
@patch("update.restore")
@patch("update.backup")
def test_run_update_refuses_non_newer_version_without_force(
    mock_backup, mock_restore, mock_subprocess_run, mock_run_store_migrate, mock_healthcheck,
    tmp_path, monkeypatch,
):
    import update
    bundle_path, public_key_path = _make_signed_bundle(tmp_path, version=1)
    monkeypatch.setattr(update, "PUBLIC_KEY_PATH", public_key_path)
    monkeypatch.setattr(update, "read_version_state", lambda: {"version": 1})

    with pytest.raises(RuntimeError, match="not newer"):
        update.run_update(bundle_path)

    mock_backup.run_backup.assert_not_called()


@patch("update.healthcheck_main")
@patch("update.run_store_migrate")
@patch("update.subprocess.run")
@patch("update.restore")
@patch("update.backup")
def test_run_update_force_applies_non_newer_version(
    mock_backup, mock_restore, mock_subprocess_run, mock_run_store_migrate, mock_healthcheck,
    tmp_path, monkeypatch,
):
    import update
    bundle_path, public_key_path = _make_signed_bundle(tmp_path, version=1)
    monkeypatch.setattr(update, "PUBLIC_KEY_PATH", public_key_path)
    monkeypatch.setattr(update, "read_version_state", lambda: {"version": 1})
    monkeypatch.setattr(update, "write_version_state", lambda state: None)
    mock_backup.run_backup.return_value = tmp_path / "backups" / "pre-update.tar.enc"

    update.run_update(bundle_path, force=True)  # should not raise

    mock_backup.run_backup.assert_called_once()
