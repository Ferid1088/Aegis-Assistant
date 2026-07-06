import pytest

from eval.table_ab import check_hit_at_10_gate


def test_gate_passes_at_threshold(capsys):
    check_hit_at_10_gate({"hit_at_10": 1.0})
    assert "PASSED" in capsys.readouterr().out


def test_gate_passes_above_threshold(capsys):
    check_hit_at_10_gate({"hit_at_10": 1.0}, threshold=0.9)
    assert "PASSED" in capsys.readouterr().out


def test_gate_fails_below_threshold(capsys):
    with pytest.raises(SystemExit) as exc_info:
        check_hit_at_10_gate({"hit_at_10": 0.857})
    assert exc_info.value.code == 1
    assert "FAILED" in capsys.readouterr().out
