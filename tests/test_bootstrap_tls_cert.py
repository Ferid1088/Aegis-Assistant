import stat

from rag.bootstrap.tls_cert import ensure_tls_certificate


def test_generates_cert_and_key_when_missing(tmp_path):
    certs_dir = tmp_path / "certs"

    ensure_tls_certificate(certs_dir)

    assert (certs_dir / "cert.pem").exists()
    assert (certs_dir / "key.pem").exists()
    cert_bytes = (certs_dir / "cert.pem").read_bytes()
    assert cert_bytes.startswith(b"-----BEGIN CERTIFICATE-----")
    key_bytes = (certs_dir / "key.pem").read_bytes()
    assert key_bytes.startswith(b"-----BEGIN PRIVATE KEY-----")


def test_generated_key_is_owner_read_write_only(tmp_path):
    certs_dir = tmp_path / "certs"

    ensure_tls_certificate(certs_dir)

    key_path = certs_dir / "key.pem"
    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600


def test_does_not_overwrite_an_existing_certificate(tmp_path):
    certs_dir = tmp_path / "certs"
    certs_dir.mkdir()
    (certs_dir / "cert.pem").write_bytes(b"existing-cert-content")
    (certs_dir / "key.pem").write_bytes(b"existing-key-content")

    ensure_tls_certificate(certs_dir)

    assert (certs_dir / "cert.pem").read_bytes() == b"existing-cert-content"
    assert (certs_dir / "key.pem").read_bytes() == b"existing-key-content"


def test_the_generated_cert_and_key_are_a_matched_pair(tmp_path):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    certs_dir = tmp_path / "certs"
    ensure_tls_certificate(certs_dir)

    key = serialization.load_pem_private_key((certs_dir / "key.pem").read_bytes(), password=None)
    from cryptography import x509
    cert = x509.load_pem_x509_certificate((certs_dir / "cert.pem").read_bytes())

    # Sign something with the private key, verify with the cert's own public key --
    # proves they're a real matched pair, not two independently generated artifacts.
    message = b"test-message"
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    cert.public_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
