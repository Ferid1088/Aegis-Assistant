"""Maintainer-side script: signs an unsigned bundle directory (produced by
build_bundle.py) and assembles the final, signed bundle tar that update.py consumes.
"""

import argparse
import json
import tarfile
from pathlib import Path

from rag.update.bundle_signing import sign_manifest


def sign_bundle(bundle_dir: Path, private_key_path: Path = Path("keys/update_signing_privkey.pem")) -> Path:
    bundle_dir = Path(bundle_dir)

    manifest_bytes = (bundle_dir / "manifest.json").read_bytes()
    signature = sign_manifest(manifest_bytes, private_key_path)
    (bundle_dir / "manifest.sig").write_bytes(signature)

    manifest = json.loads(manifest_bytes)
    output_path = Path(f"appliance-update-v{manifest['version']}.tar")

    with tarfile.open(output_path, "w") as tar:
        for item in sorted(bundle_dir.iterdir()):
            tar.add(item, arcname=item.name)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Sign an unsigned bundle directory")
    parser.add_argument("bundle_dir", type=Path)
    args = parser.parse_args()

    output_path = sign_bundle(args.bundle_dir)
    print(f"Signed bundle written to {output_path}")


if __name__ == "__main__":
    main()
