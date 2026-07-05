"""One-time maintainer script: generates the Ed25519 keypair used to sign and verify
update bundles. Run this once, keep the private key OUTSIDE the repo (a secrets vault,
an encrypted USB key -- anywhere but git), and commit only the public key.
"""

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keypair(keys_dir: Path = Path("keys")) -> tuple[Path, Path]:
    keys_dir = Path(keys_dir)
    keys_dir.mkdir(parents=True, exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_path = keys_dir / "update_signing_privkey.pem"
    public_path = keys_dir / "update_signing_pubkey.pem"

    private_path.write_bytes(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    public_path.write_bytes(public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))

    return private_path, public_path


def main():
    private_path, public_path = generate_keypair()
    print(f"Private key written to {private_path} -- move this OUTSIDE the repo now, "
          "it must never be committed.")
    print(f"Public key written to {public_path} -- safe to commit, ships in every appliance image.")


if __name__ == "__main__":
    main()
