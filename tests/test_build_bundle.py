import json
from unittest.mock import call, patch

from build_bundle import build_bundle


@patch("build_bundle.subprocess.run")
def test_build_bundle_builds_and_saves_both_images(mock_run, tmp_path):
    output_dir = tmp_path / "bundle-build"

    # subprocess.run is mocked, so `docker save -o <path>` won't really create the
    # file -- create empty placeholder files ourselves so sha256_file has something
    # real to hash.
    def fake_run(cmd, **kwargs):
        if cmd[0:2] == ["docker", "save"]:
            out_path = cmd[cmd.index("-o") + 1]
            open(out_path, "wb").close()
        return None

    mock_run.side_effect = fake_run

    build_bundle(version=3, changelog="test release", output_dir=output_dir)

    build_calls = [c for c in mock_run.call_args_list if c.args[0][0:2] == ["docker", "build"]]
    assert len(build_calls) == 2
    tags_built = {c.args[0][c.args[0].index("-t") + 1] for c in build_calls}
    assert tags_built == {"rag-appliance-worker:v3", "rag-appliance-app:v3"}


@patch("build_bundle.subprocess.run")
def test_build_bundle_writes_a_valid_manifest(mock_run, tmp_path):
    output_dir = tmp_path / "bundle-build"

    def fake_run(cmd, **kwargs):
        if cmd[0:2] == ["docker", "save"]:
            out_path = cmd[cmd.index("-o") + 1]
            with open(out_path, "wb") as f:
                f.write(b"fake-image-bytes")
        return None

    mock_run.side_effect = fake_run

    build_bundle(version=5, changelog="adds feature X", output_dir=output_dir)

    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["version"] == 5
    assert manifest["changelog"] == "adds feature X"
    assert set(manifest["files"].keys()) == {"worker-image.tar", "app-image.tar"}
    for expected_hash in manifest["files"].values():
        assert expected_hash.startswith("sha256:")
