from unittest.mock import patch

import pytest


@patch("rollback.subprocess.run")
@patch("rollback.restore")
def test_run_rollback_restores_previous_state(mock_restore, mock_subprocess_run, monkeypatch):
    import rollback

    state = {
        "version": 2,
        "images": {"worker": "rag-appliance-worker:v2", "app": "rag-appliance-app:v2"},
        "previous": {
            "version": 1,
            "images": {"worker": "rag-appliance-worker:v1", "app": "rag-appliance-app:v1"},
            "backup_path": "backups/pre-update-v2.tar.enc",
        },
    }
    monkeypatch.setattr(rollback, "read_version_state", lambda: state)
    written_state = {}
    monkeypatch.setattr(rollback, "write_version_state", lambda s: written_state.update(s))

    rollback.run_rollback()

    mock_restore.run_restore.assert_called_once()
    restored_path = mock_restore.run_restore.call_args.args[0]
    assert str(restored_path) == "backups/pre-update-v2.tar.enc"
    assert written_state["version"] == 1
    assert "previous" not in written_state

    tag_calls = [c for c in mock_subprocess_run.call_args_list if c.args[0][0:2] == ["docker", "tag"]]
    assert len(tag_calls) == 2


@patch("rollback.subprocess.run")
@patch("rollback.restore")
def test_run_rollback_refuses_when_nothing_to_roll_back_to(mock_restore, mock_subprocess_run, monkeypatch):
    import rollback

    monkeypatch.setattr(rollback, "read_version_state", lambda: {"version": 1})

    with pytest.raises(RuntimeError, match="[Nn]othing to roll back"):
        rollback.run_rollback()

    mock_restore.run_restore.assert_not_called()
