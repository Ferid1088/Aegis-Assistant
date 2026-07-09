"""Pure, side-effect-free helpers for aggregating Ragas eval results.

Deliberately kept in its own module, separate from eval/run_eval.py: run_eval.py's
module-level code patches `sys.modules["langchain_community.chat_models.vertexai"]`
and calls `nest_asyncio.apply()` *before* importing ragas (both needed to make
ragas importable and usable at all on this repo's dependency pins -- see
run_eval.py's own comments). Those are real, global process-wide side effects:
`nest_asyncio.apply()` patches the default asyncio event loop for the rest of the
process. Importing `eval.run_eval` from a unit test -- even just to reach this one
pure function -- was confirmed (see task-4-report.md, Phase 8.8 Task 4) to corrupt
FastAPI TestClient/httpx/anyio's event-loop behavior for every other test in the
same pytest session once that import happens during pytest's collection phase
(collection imports every test module before any test runs), breaking ~87
unrelated router tests. Keeping this function here, with no ragas/nest_asyncio
imports at all, lets it be unit-tested in isolation without that blast radius.
"""

import pandas as pd


def aggregate_metric_columns(df: pd.DataFrame, metric_cols: list[str]) -> dict[str, float]:
    """Mean-aggregate each metric column, tolerating columns where every value
    failed to score.

    ragas.executor.Executor catches each per-row metric-scoring exception and
    substitutes np.nan (see ragas/executor.py's wrap_callable_with_index) --
    when EVERY row for a given metric fails this way (reproduced here: ragas
    0.2.12's own executor.py unconditionally calls nest_asyncio.apply() at
    import time, which breaks Python 3.14's asyncio.wait_for()/asyncio.timeout()
    task-context check with RuntimeError("Timeout should be used inside a
    task") -- independent of this repo's own code), pandas can infer the
    resulting all-NaN/mixed column using its "string" dtype rather than
    float64, and a plain `.mean()` raises TypeError("Cannot perform reduction
    'mean' with string dtype") instead of just yielding no score. Coercing with
    pd.to_numeric(..., errors="coerce") first normalizes any such column to
    numeric (turning anything non-numeric into NaN) so a metric that's
    entirely unscored is safely omitted, matching this report-only step's
    design intent: it must complete and write a report regardless of the
    Ragas numbers.
    """
    agg_scores = {}
    for col in metric_cols:
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(vals) > 0:
            agg_scores[col] = float(vals.mean())
    return agg_scores
