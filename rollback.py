"""Rolls back to the appliance's previous version: retags the prior images, restarts
services, and restores the backup taken immediately before the update being undone.
Only one level of history is kept -- running this twice in a row without an
intervening update refuses, since 'previous' is cleared after a successful rollback.
"""

import subprocess

import restore
from rag.update.version_state import read_version_state, write_version_state

IMAGES = {"worker": "rag-appliance-worker", "app": "rag-appliance-app"}


def run_rollback() -> None:
    state = read_version_state()
    previous = state.get("previous")
    if not previous:
        raise RuntimeError("Nothing to roll back to -- no prior update recorded.")

    print(f"Rolling back to version {previous['version']}...")
    for name, image_name in IMAGES.items():
        versioned_tag = previous["images"][name]
        subprocess.run(["docker", "tag", versioned_tag, f"{image_name}:latest"], check=True)

    subprocess.run(["docker", "compose", "up", "-d"], check=True)

    print(f"Restoring backup from {previous['backup_path']}...")
    restore.run_restore(previous["backup_path"])

    write_version_state({
        "version": previous["version"],
        "images": previous["images"],
    })

    print(f"\n🎉 Rolled back to version {previous['version']}.")


def main():
    run_rollback()


if __name__ == "__main__":
    main()
