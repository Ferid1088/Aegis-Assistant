"""Helper for writing eval run results to the observability DB."""

import subprocess

from rag.crosscutting.observability.trace_store import get_trace_store


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _get_store():
    return get_trace_store()


def write_eval_run(kind: str, metrics: dict) -> str:
    """Write an eval_runs row. Returns run_id."""
    return _get_store().write_eval_run(
        kind=kind,
        metrics=metrics,
        git_commit=_git_commit(),
    )
