"""Regression tests for a real bug found while wiring up the `eval-harness` CI job
(Phase 8.8, Task 4): `rag` is not an installed package (no [build-system] table in
pyproject.toml) -- it is only importable because the repo root happens to be on
sys.path. When a script is executed directly (`uv run python eval/<script>.py`,
exactly as the CI job does), Python sets sys.path[0] to the *script's own
directory* (`eval/`), not the repo root or the caller's cwd -- so `from rag...`
imports in any eval/*.py script raised `ModuleNotFoundError: No module named 'rag'`
regardless of where the command was run from.

`eval/eval_report.py` already carried a `sys.path.insert(0, str(Path(__file__).parent.parent))`
fix for this exact problem; `eval/table_ab.py`, `eval/ingest_variant_b.py`, and
`eval/run_eval.py` -- all invoked directly by the eval-harness CI job -- did not,
and reproducibly failed on a first invocation from a clean shell (confirmed
independently of any CI/act artifact: `uv run python eval/table_ab.py --collection
documents_tabstruct` from the repo root raised the same ModuleNotFoundError before
the fix below was applied).

These tests invoke each fixed script as a real subprocess, with PYTHONPATH
deliberately stripped and cwd set to a directory that is NOT the repo root (a
tmp_path), to prove the fix resolves `rag` purely from the script's own file
location (__file__), not from cwd or an inherited environment variable -- the
same way `uv run python eval/<script>.py` is invoked in .github/workflows/ci.yml.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _run(rel_path: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / rel_path), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_table_ab_resolves_rag_import_without_pythonpath(tmp_path):
    # --help exits (via argparse) before touching Qdrant/CrossEncoder/the LLM --
    # this only proves the import machinery works, not full runtime behavior
    # (covered separately, at length, by the real eval-harness CI job).
    proc = _run("eval/table_ab.py", ["--help"], cwd=tmp_path)
    assert "ModuleNotFoundError" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stderr
    assert "usage: table_ab.py" in proc.stdout


def test_ingest_variant_b_resolves_rag_import_without_pythonpath(tmp_path):
    # cwd (tmp_path) deliberately has no docs/TV_L_tables.json, so the script's
    # own early-return path ("not found") fires right after the module-level
    # imports succeed -- proving those imports resolved without touching Qdrant
    # or downloading embedding models.
    proc = _run("eval/ingest_variant_b.py", [], cwd=tmp_path)
    assert "ModuleNotFoundError" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stderr
    assert "docs/TV_L_tables.json not found" in proc.stdout


def test_run_eval_resolves_rag_import_without_pythonpath(tmp_path):
    # cwd (tmp_path) deliberately has no eval/golden_set.jsonl, so main() raises
    # FileNotFoundError trying to open it -- proving the module-level `from
    # rag.pipelines.retrieval.graph import build_query_graph` (and the heavier ragas/datasets
    # imports before it) already resolved cleanly.
    proc = _run("eval/run_eval.py", [], cwd=tmp_path)
    assert "ModuleNotFoundError: No module named 'rag'" not in proc.stderr, proc.stderr
    assert proc.returncode != 0
    assert "FileNotFoundError" in proc.stderr
    assert "golden_set.jsonl" in proc.stderr
