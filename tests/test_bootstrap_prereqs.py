from unittest.mock import MagicMock, patch

import pytest

from rag.bootstrap.prereqs import check_docker, check_gpu, check_ram


@patch("rag.bootstrap.prereqs.subprocess.run")
def test_check_docker_passes_when_both_commands_succeed(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    check_docker()  # must not raise
    assert mock_run.call_count == 2


@patch("rag.bootstrap.prereqs.subprocess.run")
def test_check_docker_raises_when_docker_missing(mock_run):
    import subprocess as real_subprocess
    mock_run.side_effect = FileNotFoundError("docker not found")

    with pytest.raises(RuntimeError, match="[Dd]ocker"):
        check_docker()


@patch("rag.bootstrap.prereqs.psutil.virtual_memory")
def test_check_ram_does_not_raise_when_below_floor(mock_vmem, capsys):
    mock_vmem.return_value = MagicMock(total=4 * 1024**3)  # 4 GB
    check_ram()  # must not raise
    captured = capsys.readouterr()
    assert "warning" in captured.out.lower() or "8" in captured.out


@patch("rag.bootstrap.prereqs.psutil.virtual_memory")
def test_check_ram_prints_ok_when_above_floor(mock_vmem, capsys):
    mock_vmem.return_value = MagicMock(total=16 * 1024**3)  # 16 GB
    check_ram()  # must not raise
    captured = capsys.readouterr()
    assert "16" in captured.out or "OK" in captured.out or "ok" in captured.out.lower()


@patch("rag.bootstrap.prereqs.shutil.which")
def test_check_gpu_reports_no_gpu_when_nvidia_smi_absent(mock_which, capsys):
    mock_which.return_value = None
    check_gpu()  # must not raise
    captured = capsys.readouterr()
    assert "No GPU" in captured.out


@patch("rag.bootstrap.prereqs.shutil.which")
def test_check_gpu_reports_gpu_when_nvidia_smi_present(mock_which, capsys):
    mock_which.return_value = "/usr/bin/nvidia-smi"
    check_gpu()  # must not raise
    captured = capsys.readouterr()
    assert "GPU detected" in captured.out
