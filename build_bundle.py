"""Maintainer-side script: builds the worker and app Docker images, saves them to
tarballs, and writes an unsigned manifest.json declaring their sha256 hashes. Run
sign_bundle.py on the resulting directory next to produce the final signed bundle.
"""

import argparse
import json
import subprocess
from pathlib import Path

from rag.update.bundle_signing import sha256_file

IMAGES = {
    "worker": "rag-appliance-worker",
    "app": "rag-appliance-app",
}


def _build_and_save_image(name: str, image_name: str, version: int, output_dir: Path) -> Path:
    tag = f"{image_name}:v{version}"
    subprocess.run(["docker", "build", "-t", tag, "."], check=True)

    tar_path = output_dir / f"{name}-image.tar"
    subprocess.run(["docker", "save", "-o", str(tar_path), tag], check=True)
    return tar_path


def build_bundle(version: int, changelog: str, output_dir: Path = Path("bundle-build")) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {}
    for name, image_name in IMAGES.items():
        tar_path = _build_and_save_image(name, image_name, version, output_dir)
        files[f"{name}-image.tar"] = sha256_file(tar_path)

    manifest = {"version": version, "changelog": changelog, "files": files}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Build an unsigned update bundle")
    parser.add_argument("version", type=int)
    parser.add_argument("changelog")
    args = parser.parse_args()

    output_dir = build_bundle(args.version, args.changelog)
    print(f"Unsigned bundle assembled at {output_dir} -- run sign_bundle.py on it next.")


if __name__ == "__main__":
    main()
