import json
from unittest.mock import patch

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
def test_build_bundle_docker_save_uses_correct_tag_and_path_per_image(mock_run, tmp_path):
    """Verify that docker save uses the correct tag/output-path pairing for each image.

    A bug that saved the wrong image's tag into the wrong tar filename (e.g.,
    swapping worker/app) would NOT be caught without this assertion.
    """
    output_dir = tmp_path / "bundle-build"

    def fake_run(cmd, **kwargs):
        if cmd[0:2] == ["docker", "save"]:
            out_path = cmd[cmd.index("-o") + 1]
            open(out_path, "wb").close()
        return None

    mock_run.side_effect = fake_run

    build_bundle(version=7, changelog="test release", output_dir=output_dir)

    # Extract all docker save calls
    save_calls = [c for c in mock_run.call_args_list if c.args[0][0:2] == ["docker", "save"]]
    assert len(save_calls) == 2, "Should have exactly 2 docker save calls (worker and app)"

    # Map each save call by its output path to extract and verify tag/path pairing
    for save_call in save_calls:
        cmd = save_call.args[0]
        out_path = cmd[cmd.index("-o") + 1]
        tag = cmd[-1]  # tag is the last positional argument

        # Extract image name from the tar filename and tag for cross-verification
        if "worker-image.tar" in out_path:
            assert tag == "rag-appliance-worker:v7", (
                f"worker-image.tar should be saved using rag-appliance-worker tag, "
                f"but got {tag}"
            )
            assert out_path.endswith("worker-image.tar"), (
                f"worker save path should end with worker-image.tar, got {out_path}"
            )
        elif "app-image.tar" in out_path:
            assert tag == "rag-appliance-app:v7", (
                f"app-image.tar should be saved using rag-appliance-app tag, "
                f"but got {tag}"
            )
            assert out_path.endswith("app-image.tar"), (
                f"app save path should end with app-image.tar, got {out_path}"
            )
        else:
            raise AssertionError(f"Unexpected output path: {out_path}")


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
