"""Ed25519 signing and verification for update bundles. `sign_manifest` is used by
the maintainer-side `sign_bundle.py`; `verify_manifest_signature` and
`verify_file_hashes` are used by the customer-side `update.py`. `sha256_file` is
shared by both the build side (Task 5) and this verification side, so hash
computation can never drift between the two.
"""

import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def sign_manifest(manifest_bytes: bytes, private_key_path: Path) -> bytes:
    private_key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
    return private_key.sign(manifest_bytes)


def verify_manifest_signature(manifest_bytes: bytes, signature: bytes, public_key_path: Path) -> bool:
    public_key = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
    try:
        public_key.verify(signature, manifest_bytes)
        return True
    except InvalidSignature:
        return False


def verify_file_hashes(manifest: dict, bundle_dir: Path) -> list[str]:
    bundle_dir = Path(bundle_dir)
    mismatches = []
    for filename, expected_hash in manifest["files"].items():
        actual_hash = sha256_file(bundle_dir / filename)
        if actual_hash != expected_hash:
            mismatches.append(filename)
    return mismatches
