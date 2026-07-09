from rag.bootstrap.env_writer import read_env_value, write_missing_env_vars


def test_writes_all_values_to_a_fresh_file(tmp_path):
    env_path = tmp_path / ".env"
    written = write_missing_env_vars(env_path, {"FOO": "bar", "BAZ": "qux"})

    content = env_path.read_text()
    assert "FOO=bar" in content
    assert "BAZ=qux" in content
    assert set(written) == {"FOO", "BAZ"}


def test_skips_keys_already_present(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=existing-value\n")

    written = write_missing_env_vars(env_path, {"FOO": "new-value", "BAZ": "qux"})

    content = env_path.read_text()
    assert "FOO=existing-value" in content
    assert "FOO=new-value" not in content
    assert "BAZ=qux" in content
    assert written == ["BAZ"]


def test_no_op_when_all_keys_already_present(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=a\nBAZ=b\n")

    written = write_missing_env_vars(env_path, {"FOO": "new", "BAZ": "new"})

    assert written == []
    content = env_path.read_text()
    assert "FOO=a" in content
    assert "BAZ=b" in content


def test_ignores_commented_out_keys(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# FOO=commented-out\n")

    written = write_missing_env_vars(env_path, {"FOO": "real-value"})

    assert written == ["FOO"]
    assert "FOO=real-value" in env_path.read_text()


def test_read_env_value_returns_none_for_missing_file(tmp_path):
    env_path = tmp_path / ".env"
    assert read_env_value(env_path, "FOO") is None


def test_read_env_value_returns_none_for_missing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n")
    assert read_env_value(env_path, "BAZ") is None


def test_read_env_value_returns_the_value(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\nBAZ=qux\n")
    assert read_env_value(env_path, "BAZ") == "qux"


def test_read_env_value_ignores_commented_out_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# FOO=commented-out\nFOO=real-value\n")
    assert read_env_value(env_path, "FOO") == "real-value"
