"use client";

import { useApi } from "@/hooks/use-api";
import { Card, EmptyState, PageTitle } from "@/components/ui/primitives";

type RawEvalRun = { run_id: string; kind: string; metrics: Record<string, number | string>; git_commit: string; ts: string };

const METRIC_KEYS = ["faithfulness", "precision", "recall", "hit_at_k"] as const;

function formatMetric(value: number | string | undefined): string {
    if (value === undefined || value === null) return "—";
    if (typeof value === "number") return value.toFixed(3);
    return String(value);
}

export function EvaluationView() {
    const { data, loading } = useApi<RawEvalRun[]>("/admin/eval-runs");
    const runs = data ?? [];

    return (
        <div className="mx-auto max-w-5xl p-6">
            <PageTitle sub="RAGAS-based offline evaluation runs (eval/run_eval.py) against the golden query set.">Evaluation</PageTitle>

            <Card className="p-5">
                {loading ? <p className="text-sm text-inkFaint">Loading…</p> : null}
                {!loading && !runs.length ? (
                    <EmptyState
                        title="No evaluation runs yet"
                        hint="Run `uv run python eval/run_eval.py` to score retrieval/generation quality against the golden set — results appear here automatically."
                    />
                ) : null}
                {runs.length ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm">
                            <thead>
                                <tr className="text-[11px] uppercase tracking-wider text-inkFaint">
                                    <th className="pb-2 pr-4 font-medium">Run</th>
                                    <th className="pb-2 pr-4 font-medium">Kind</th>
                                    {METRIC_KEYS.map((key) => (
                                        <th key={key} className="pb-2 pr-4 font-medium capitalize">{key.replace("_", " ")}</th>
                                    ))}
                                    <th className="pb-2 pr-4 font-medium">Commit</th>
                                    <th className="pb-2 font-medium">When</th>
                                </tr>
                            </thead>
                            <tbody>
                                {runs.map((run) => (
                                    <tr key={run.run_id} className="border-t border-line/70">
                                        <td className="py-2 pr-4 font-mono text-[12px] text-inkSoft">{run.run_id.slice(0, 8)}</td>
                                        <td className="py-2 pr-4 text-ink">{run.kind}</td>
                                        {METRIC_KEYS.map((key) => (
                                            <td key={key} className="py-2 pr-4 text-ink">{formatMetric(run.metrics[key])}</td>
                                        ))}
                                        <td className="py-2 pr-4 font-mono text-[12px] text-inkFaint">{run.git_commit}</td>
                                        <td className="py-2 text-inkFaint">{new Date(run.ts).toLocaleString()}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : null}
            </Card>
        </div>
    );
}
