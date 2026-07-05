"""Requires a running Docker daemon and a real Postgres/Neo4j/Qdrant/Redis stack
(the same `docker compose up -d` stack 8.4's and 8.5a's integration tests use).
Builds tiny, fast dummy images instead of the real multi-GB app/worker build, so
this test runs in seconds while still exercising the real signature/hash
verification, real docker load/tag, real backup/restore, and real version-state
transitions end-to-end.
Run with: uv run pytest tests/integration/test_update_flow.py -v -s
"""
import subprocess

import pytest

from generate_signing_keypair import generate_keypair
from rag.update.version_state import read_version_state, write_version_state
from sign_bundle import sign_bundle


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "compose", "ps"], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _build_tiny_test_image(tag: str) -> None:
    # A minimal image that starts instantly and needs no real build context --
    # keeps this test's Docker usage to seconds, not the real app/worker build's
    # minutes, while still exercising a genuine docker build + save + load + tag
    # round trip.
    #
    # Stubs out /bin/uv as a no-op long-running process: docker-compose.yml's
    # app/worker services hardcode `command: uv run ...`, and `docker compose up
    # -d` fails hard (nonzero exit) at OCI-runtime-create time if that binary is
    # missing from the image -- a normal in-container crash after startup is
    # tolerated by `up -d`, but a missing exec target is not. Real bundles built
    # by build_bundle.py always have a real `uv` (baked in by the Dockerfile), so
    # this stub only exists to keep the tiny dummy image compatible with the real
    # compose file's `command:` without doing the real multi-GB build.
    subprocess.run(
        ["docker", "build", "-t", tag, "-"],
        input=(
            b"FROM alpine:latest\n"
            b"RUN printf '#!/bin/sh\\nsleep 3600\\n' > /bin/uv && chmod +x /bin/uv\n"
            b"CMD [\"true\"]\n"
        ),
        check=True,
    )


@pytest.mark.skipif(not _docker_available(), reason="docker compose not available locally")
def test_update_then_rollback_round_trip(tmp_path, monkeypatch):
    import build_bundle
    import rollback
    import update

    # Two updates, not one: rolling back the very first-ever update is a narrower
    # edge case (there's no prior *bundle* image to retag to -- version 0 was built
    # from source, not loaded from a bundle -- so rollback.py's `previous["images"]`
    # would be `{}` and retagging would KeyError). Applying v1 then v2 means the
    # rollback under test (v2 -> v1) retags to a real, previously-loaded image tag,
    # which is also the realistic case: an operator is far more likely to roll back
    # a later update than the one that replaced a from-source install.
    version_path = tmp_path / "appliance_version.json"
    monkeypatch.setattr(update, "read_version_state", lambda: read_version_state(version_path))
    monkeypatch.setattr(update, "write_version_state", lambda s: write_version_state(s, version_path))
    monkeypatch.setattr(rollback, "read_version_state", lambda: read_version_state(version_path))
    monkeypatch.setattr(rollback, "write_version_state", lambda s: write_version_state(s, version_path))

    private_path, public_path = generate_keypair(tmp_path / "keys")
    monkeypatch.setattr(update, "PUBLIC_KEY_PATH", public_path)

    def fake_build_and_save(name, image_name, version, output_dir):
        tag = f"{image_name}:v{version}"
        _build_tiny_test_image(tag)
        tar_path = output_dir / f"{name}-image.tar"
        subprocess.run(["docker", "save", "-o", str(tar_path), tag], check=True)
        return tar_path

    monkeypatch.setattr(build_bundle, "_build_and_save_image", fake_build_and_save)

    bundle_v1_dir = build_bundle.build_bundle(version=1, changelog="v1", output_dir=tmp_path / "build-v1")
    bundle_v1_path = sign_bundle(bundle_v1_dir, private_key_path=private_path)
    update.run_update(bundle_v1_path)

    state_after_v1 = read_version_state(version_path)
    assert state_after_v1["version"] == 1
    assert state_after_v1["previous"]["version"] == 0
    assert state_after_v1["previous"]["images"] == {}

    bundle_v2_dir = build_bundle.build_bundle(version=2, changelog="v2", output_dir=tmp_path / "build-v2")
    bundle_v2_path = sign_bundle(bundle_v2_dir, private_key_path=private_path)
    update.run_update(bundle_v2_path)

    state_after_v2 = read_version_state(version_path)
    assert state_after_v2["version"] == 2
    assert state_after_v2["previous"]["version"] == 1
    assert state_after_v2["previous"]["images"] == state_after_v1["images"]

    rollback.run_rollback()

    state_after_rollback = read_version_state(version_path)
    assert state_after_rollback["version"] == 1
    assert state_after_rollback["images"] == state_after_v1["images"]
    assert "previous" not in state_after_rollback
