"""Regression test for a real bug found while verifying the `eval-harness` CI job
(Phase 8.8, Task 4): `eval/run_eval.py` crashed with

    TypeError: Cannot perform reduction 'mean' with string dtype

whenever every Ragas job for a given metric failed to score. Root cause,
independently reproduced (see task-4-report.md): ragas==0.2.12's own
ragas/executor.py unconditionally calls `nest_asyncio.apply()` at import time,
which breaks Python 3.14's `asyncio.wait_for()`/`asyncio.timeout()` task-context
tracking with `RuntimeError("Timeout should be used inside a task")` --
independent of this repo's own code, and independent of any CI/act artifact
(reproduced with a minimal standalone asyncio + nest_asyncio script). When
every job for a metric column fails this way, ragas.executor.Executor
substitutes np.nan per row, but pandas can infer the resulting column as its
"string" dtype rather than float64 -- and a plain `.mean()` raises TypeError
instead of yielding no score.

This is orthogonal to the eval-harness job's own design intent: `run_eval.py`
is a report-only step (no threshold gate) that must complete and write a
report regardless of the actual Ragas numbers -- a metric column that's
entirely unscored should be omitted from the aggregate, not crash the run.

NOTE: this test deliberately imports `aggregate_metric_columns` from
eval/eval_aggregation.py, NOT eval/run_eval.py, even though the function used
to live in run_eval.py itself. Importing eval.run_eval directly from a test
was confirmed (during this same investigation) to corrupt global process state
-- its module-level code patches sys.modules and calls nest_asyncio.apply()
(needed to make ragas importable/usable at all here), and nest_asyncio.apply()
patches the default asyncio event loop for the rest of the process. Since
pytest imports every test module during collection (before running any test),
that one import broke ~87 unrelated FastAPI TestClient-based tests in the same
session. The pure aggregation logic was extracted into its own
eval/eval_aggregation.py with no such side effects specifically so it could be
unit-tested without that blast radius -- don't import eval.run_eval here.
"""
import numpy as np
import pandas as pd
import pytest

from eval.eval_aggregation import aggregate_metric_columns


def test_all_nan_metric_column_is_omitted_not_crashed():
    # Reproduces the real failure: every job for "faithfulness" failed (np.nan
    # for every row), which can surface as a non-numeric ("string") dtype column
    # rather than float64 -- the exact shape that broke a plain Series.mean().
    df = pd.DataFrame({
        "question": ["q1", "q2"],
        "faithfulness": pd.array([None, None], dtype="string"),
        "answer_relevancy": [0.8, 0.6],
    })

    agg = aggregate_metric_columns(df, ["faithfulness", "answer_relevancy"])

    assert "faithfulness" not in agg
    assert agg["answer_relevancy"] == pytest.approx(0.7)


def test_all_metrics_failed_yields_empty_aggregate_not_a_crash():
    # The exact real-world shape hit during verification: every metric, every
    # row, failed -- the aggregate must come back empty, not raise.
    df = pd.DataFrame({
        "question": ["q1", "q2", "q3", "q4"],
        "faithfulness": pd.array([None, None, None, None], dtype="string"),
        "answer_relevancy": pd.array([None, None, None, None], dtype="string"),
        "context_precision": pd.array([None, None, None, None], dtype="string"),
        "context_recall": pd.array([None, None, None, None], dtype="string"),
    })

    agg = aggregate_metric_columns(
        df, ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    )

    assert agg == {}


def test_normal_numeric_columns_still_aggregate_correctly():
    df = pd.DataFrame({
        "question": ["q1", "q2"],
        "faithfulness": [1.0, np.nan],
        "answer_relevancy": [0.5, 0.9],
    })

    agg = aggregate_metric_columns(df, ["faithfulness", "answer_relevancy"])

    assert agg["faithfulness"] == pytest.approx(1.0)
    assert agg["answer_relevancy"] == pytest.approx(0.7)

