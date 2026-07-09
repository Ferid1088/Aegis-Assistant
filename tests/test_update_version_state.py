import json

from rag.update.version_state import read_version_state, write_version_state


def test_read_returns_default_when_file_missing(tmp_path):
    version_path = tmp_path / "appliance_version.json"
    assert read_version_state(version_path) == {"version": 0}


def test_write_then_read_round_trips(tmp_path):
    version_path = tmp_path / "appliance_version.json"
    state = {"version": 2, "images": {"worker": "rag-appliance-worker:v2"}}

    write_version_state(state, version_path)

    assert read_version_state(version_path) == state


def test_write_creates_parent_directories(tmp_path):
    version_path = tmp_path / "nested" / "dir" / "appliance_version.json"

    write_version_state({"version": 1}, version_path)

    assert version_path.exists()
    assert json.loads(version_path.read_text()) == {"version": 1}


def test_write_overwrites_existing_file(tmp_path):
    version_path = tmp_path / "appliance_version.json"
    write_version_state({"version": 1}, version_path)

    write_version_state({"version": 2}, version_path)

    assert read_version_state(version_path) == {"version": 2}
