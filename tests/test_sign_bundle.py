import json
import tarfile

from generate_signing_keypair import generate_keypair
from rag.update.bundle_signing import verify_manifest_signature
from sign_bundle import sign_bundle


def _make_unsigned_bundle(bundle_dir):
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 7, "changelog": "test", "files": {"worker-image.tar": "sha256:abc"}}
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest))
    (bundle_dir / "worker-image.tar").write_bytes(b"fake-image-bytes")


def test_sign_bundle_writes_a_valid_signature(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    private_path, public_path = generate_keypair(tmp_path / "keys")
    bundle_dir = tmp_path / "bundle-build"
    _make_unsigned_bundle(bundle_dir)

    sign_bundle(bundle_dir, private_key_path=private_path)

    manifest_bytes = (bundle_dir / "manifest.json").read_bytes()
    signature = (bundle_dir / "manifest.sig").read_bytes()
    assert verify_manifest_signature(manifest_bytes, signature, public_path) is True


def test_sign_bundle_produces_a_tar_containing_everything(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    private_path, _ = generate_keypair(tmp_path / "keys")
    bundle_dir = tmp_path / "bundle-build"
    _make_unsigned_bundle(bundle_dir)

    output_path = sign_bundle(bundle_dir, private_key_path=private_path)

    assert output_path.name == "appliance-update-v7.tar"
    with tarfile.open(output_path) as tar:
        names = set(tar.getnames())
    assert names == {"manifest.json", "manifest.sig", "worker-image.tar"}
