from generate_signing_keypair import generate_keypair
from rag.update.bundle_signing import (
    sha256_file, sign_manifest, verify_file_hashes, verify_manifest_signature,
)


def test_sha256_file_matches_known_hash(tmp_path):
    file_path = tmp_path / "data.bin"
    file_path.write_bytes(b"hello world")

    # sha256("hello world") is a well-known test vector
    assert sha256_file(file_path) == (
        "sha256:b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )


def test_sign_and_verify_round_trip(tmp_path):
    private_path, public_path = generate_keypair(tmp_path / "keys")
    manifest_bytes = b'{"version": 1}'

    signature = sign_manifest(manifest_bytes, private_path)

    assert verify_manifest_signature(manifest_bytes, signature, public_path) is True


def test_verify_rejects_tampered_manifest(tmp_path):
    private_path, public_path = generate_keypair(tmp_path / "keys")
    manifest_bytes = b'{"version": 1}'
    signature = sign_manifest(manifest_bytes, private_path)

    tampered_bytes = b'{"version": 999}'

    assert verify_manifest_signature(tampered_bytes, signature, public_path) is False


def test_verify_rejects_signature_from_a_different_key(tmp_path):
    _, public_path = generate_keypair(tmp_path / "keys_a")
    other_private_path, _ = generate_keypair(tmp_path / "keys_b")
    manifest_bytes = b'{"version": 1}'

    wrong_signature = sign_manifest(manifest_bytes, other_private_path)

    assert verify_manifest_signature(manifest_bytes, wrong_signature, public_path) is False


def test_verify_file_hashes_passes_when_all_match(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "a.tar").write_bytes(b"content-a")
    (bundle_dir / "b.tar").write_bytes(b"content-b")

    manifest = {
        "files": {
            "a.tar": sha256_file(bundle_dir / "a.tar"),
            "b.tar": sha256_file(bundle_dir / "b.tar"),
        }
    }

    assert verify_file_hashes(manifest, bundle_dir) == []


def test_verify_file_hashes_flags_a_tampered_file(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "a.tar").write_bytes(b"content-a")

    manifest = {"files": {"a.tar": sha256_file(bundle_dir / "a.tar")}}

    # tamper with the file AFTER the manifest recorded its original hash
    (bundle_dir / "a.tar").write_bytes(b"tampered-content")

    assert verify_file_hashes(manifest, bundle_dir) == ["a.tar"]
