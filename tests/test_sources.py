import pytest

from rag.infra.stores.sources import ApiSource, FilesystemSource, S3Source, SharePointSource, SqliteSource, SqlSource


def test_filesystem_source_lists_matching_files(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"AAA")
    (tmp_path / "b.pdf").write_bytes(b"BBB")
    (tmp_path / "c.txt").write_bytes(b"ignored")

    source = FilesystemSource(str(tmp_path))
    items = source.list_items()
    names = sorted(item.item_id for item in items)
    assert names == sorted([str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")])


def test_filesystem_source_fetch_returns_bytes(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"hello world")
    source = FilesystemSource(str(tmp_path))
    assert source.fetch(str(f)) == b"hello world"


def test_filesystem_source_new_or_changed_detects_new_file(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"AAA")
    source = FilesystemSource(str(tmp_path))
    changed = source.new_or_changed(cursor={})
    assert len(changed) == 1
    assert changed[0].content_hash is not None


def test_filesystem_source_new_or_changed_skips_unchanged_file(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"AAA")
    source = FilesystemSource(str(tmp_path))
    first_pass = source.new_or_changed(cursor={})
    cursor = {item.item_id: item.content_hash for item in first_pass}

    second_pass = source.new_or_changed(cursor=cursor)
    assert second_pass == []


def test_filesystem_source_new_or_changed_detects_modified_file(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"AAA")
    source = FilesystemSource(str(tmp_path))
    first_pass = source.new_or_changed(cursor={})
    cursor = {item.item_id: item.content_hash for item in first_pass}

    f.write_bytes(b"CHANGED")
    second_pass = source.new_or_changed(cursor=cursor)
    assert len(second_pass) == 1


@pytest.mark.parametrize("cls", [S3Source, SqlSource, SqliteSource, ApiSource, SharePointSource])
def test_stub_sources_raise_not_implemented(cls):
    stub = cls()
    with pytest.raises(NotImplementedError):
        stub.list_items()
    with pytest.raises(NotImplementedError):
        stub.new_or_changed({})
    with pytest.raises(NotImplementedError):
        stub.fetch("x")
