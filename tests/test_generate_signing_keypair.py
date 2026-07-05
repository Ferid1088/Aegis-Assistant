from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from generate_signing_keypair import generate_keypair


def test_generate_keypair_writes_both_files(tmp_path):
    keys_dir = tmp_path / "keys"

    private_path, public_path = generate_keypair(keys_dir)

    assert private_path == keys_dir / "update_signing_privkey.pem"
    assert public_path == keys_dir / "update_signing_pubkey.pem"
    assert private_path.exists()
    assert public_path.exists()


def test_generated_keys_are_loadable_and_matched(tmp_path):
    keys_dir = tmp_path / "keys"
    private_path, public_path = generate_keypair(keys_dir)

    private_key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    public_key = serialization.load_pem_public_key(public_path.read_bytes())

    assert isinstance(private_key, Ed25519PrivateKey)

    # sign with the generated private key, verify with the generated public key --
    # proves they're a real matched pair, not two independently generated keys
    signature = private_key.sign(b"test-message")
    public_key.verify(signature, b"test-message")  # raises InvalidSignature if mismatched


def test_generate_keypair_creates_missing_directory(tmp_path):
    keys_dir = tmp_path / "does" / "not" / "exist"

    generate_keypair(keys_dir)

    assert keys_dir.exists()
