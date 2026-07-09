"""Verifies and applies a signed update bundle: backs up, loads new images,
migrates, and health-checks -- with automatic rollback to the pre-update backup if
anything fails from the image-load step onward.
"""

import argparse
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

import backup
import restore
import run_store_migrate
from rag.healthcheck import main as healthcheck_main
from rag.update.bundle_signing import verify_file_hashes, verify_manifest_signature
from rag.update.version_state import read_version_state, write_version_state

PUBLIC_KEY_PATH = Path("keys/update_signing_pubkey.pem")
IMAGES = {"worker": "rag-appliance-worker", "app": "rag-appliance-app"}


def run_update(bundle_path: Path, force: bool = False) -> None:
    bundle_path = Path(bundle_path)

    with tempfile.TemporaryDirectory() as tmp:
        extracted = Path(tmp)
        print(f"Extracting {bundle_path}...")
        with tarfile.open(bundle_path) as tar:
            tar.extractall(extracted)

        manifest_bytes = (extracted / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)

        print("Verifying bundle signature...")
        signature = (extracted / "manifest.sig").read_bytes()
        if not verify_manifest_signature(manifest_bytes, signature, PUBLIC_KEY_PATH):
            raise RuntimeError("Bundle signature is invalid -- refusing to apply.")

        print("Verifying file integrity...")
        mismatches = verify_file_hashes(manifest, extracted)
        if mismatches:
            raise RuntimeError(f"Bundle files failed integrity check: {', '.join(mismatches)}")

        current_state = read_version_state()
        current_version = current_state.get("version", 0)
        new_version = manifest["version"]
        if new_version <= current_version and not force:
            raise RuntimeError(
                f"Bundle version {new_version} is not newer than the installed version "
                f"{current_version} (use --force to apply anyway)."
            )

        print("Taking a pre-update backup...")
        backup_path = backup.run_backup()

        try:
            print("Loading new images...")
            new_images = {}
            for name, image_name in IMAGES.items():
                image_tar = extracted / f"{name}-image.tar"
                versioned_tag = f"{image_name}:v{new_version}"
                subprocess.run(["docker", "load", "-i", str(image_tar)], check=True)
                subprocess.run(["docker", "tag", versioned_tag, f"{image_name}:latest"], check=True)
                new_images[name] = versioned_tag

            print("Restarting services with the new images...")
            subprocess.run(["docker", "compose", "up", "-d"], check=True)

            print("Running migrations...")
            subprocess.run(["alembic", "upgrade", "head"], check=True)
            run_store_migrate.main()

            print("Verifying health...")
            healthcheck_main()
        except BaseException as exc:
            # BaseException, not Exception: run_store_migrate.main() calls
            # sys.exit(1) on failure, which raises SystemExit -- a subclass of
            # BaseException, not Exception. Without this, a real migration failure
            # would skip the restore below entirely.
            print(f"Update failed ({exc}) -- restoring pre-update backup...")
            restore.run_restore(backup_path)
            raise

        write_version_state({
            "version": new_version,
            "images": new_images,
            "previous": {
                "version": current_version,
                "images": current_state.get("images", {}),
                "backup_path": str(backup_path),
            },
        })

    print(f"\n🎉 Update to version {new_version} complete.")


def main():
    parser = argparse.ArgumentParser(description="Apply a signed appliance update bundle")
    parser.add_argument("bundle_path", type=Path)
    parser.add_argument("--force", action="store_true", help="Apply even if the bundle version isn't newer")
    args = parser.parse_args()
    run_update(args.bundle_path, force=args.force)


if __name__ == "__main__":
    main()
