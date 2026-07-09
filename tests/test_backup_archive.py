import tarfile

from rag.backup.archive import build_tar, decrypt_archive, encrypt_archive, extract_tar


def test_build_tar_includes_all_sources(tmp_path):
    file_source = tmp_path / "documents.db"
    file_source.write_text("fake sqlite content")
    dir_source = tmp_path / "qdrant_data"
    dir_source.mkdir()
    (dir_source / "meta.json").write_text("{}")

    output = tmp_path / "out.tar"
    build_tar({"documents.db": file_source, "qdrant": dir_source}, output)

    with tarfile.open(output) as tar:
        names = tar.getnames()
    assert "documents.db" in names
    assert any(n.startswith("qdrant/") or n == "qdrant" for n in names)


def test_encrypt_decrypt_archive_round_trip(db_session, tmp_path):
    tar_path = tmp_path / "plain.tar"
    tar_path.write_bytes(b"fake tar bytes for round-trip test")

    encrypted_path = tmp_path / "out.tar.enc"
    encrypt_archive(db_session, tar_path, encrypted_path)
    assert encrypted_path.read_bytes() != tar_path.read_bytes()

    decrypted_path = tmp_path / "decrypted.tar"
    decrypt_archive(db_session, encrypted_path, decrypted_path)
    assert decrypted_path.read_bytes() == tar_path.read_bytes()


def test_extract_tar_restores_files(tmp_path):
    source_file = tmp_path / "a.txt"
    source_file.write_text("hello")
    tar_path = tmp_path / "out.tar"
    build_tar({"a.txt": source_file}, tar_path)

    dest_dir = tmp_path / "extracted"
    extract_tar(tar_path, dest_dir)

    assert (dest_dir / "a.txt").read_text() == "hello"
