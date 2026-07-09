"use client";

import type { LatencyPoint, ServiceHealth } from "@/types";
import { useApi } from "@/hooks/use-api";
import { Card, PageTitle, Pill, StatusDot } from "@/components/ui/primitives";

type RawComponent = { name: string; status: ServiceHealth["status"]; detail: string | null };
type RawLatencyPoint = { span: string; p50: number; p95: number; p99: number };

export function SystemView() {
    const { data: statusData, loading: statusLoading } = useApi<{ components: RawComponent[] }>("/admin/system");
    const { data: latencyData, loading: latencyLoading } = useApi<RawLatencyPoint[]>("/admin/latency");

    const components = statusData?.components ?? [];
    const latency = (latencyData ?? []) as LatencyPoint[];

    return (
        <div className="mx-auto max-w-5xl p-6">
            <PageTitle sub="Live health of every backing service, plus recent pipeline latency.">System</PageTitle>

            <Card className="mb-6 p-5">
                <h2 className="mb-4 text-sm font-medium text-ink">Component status</h2>
                {statusLoading ? <p className="text-sm text-inkFaint">Loading…</p> : null}
                <div className="grid gap-2 sm:grid-cols-2">
                    {components.map((c) => (
                        <div key={c.name} className="flex items-center justify-between rounded-md border border-line/70 px-3 py-2">
                            <div className="flex items-center gap-2">
                                <StatusDot status={c.status} />
                                <span className="text-sm text-ink">{c.name}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                {c.detail ? <span className="text-[12px] text-inkFaint">{c.detail}</span> : null}
                                <Pill tone={c.status === "online" ? "online" : c.status === "degraded" ? "degraded" : "offline"}>
                                    {c.status}
                                </Pill>
                            </div>
                        </div>
                    ))}
                </div>
            </Card>

            <Card className="p-5">
                <h2 className="mb-4 text-sm font-medium text-ink">Pipeline latency (ms)</h2>
                {latencyLoading ? <p className="text-sm text-inkFaint">Loading…</p> : null}
                {!latencyLoading && !latency.length ? (
                    <p className="text-sm text-inkFaint">No spans recorded yet — run a chat query or search to populate this.</p>
                ) : null}
                {latency.length ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm">
                            <thead>
                                <tr className="text-[11px] uppercase tracking-wider text-inkFaint">
                                    <th className="pb-2 pr-4 font-medium">Span</th>
                                    <th className="pb-2 pr-4 font-medium">p50</th>
                                    <th className="pb-2 pr-4 font-medium">p95</th>
                                    <th className="pb-2 font-medium">p99</th>
                                </tr>
                            </thead>
                            <tbody>
                                {latency.map((row) => (
                                    <tr key={row.span} className="border-t border-line/70">
                                        <td className="py-2 pr-4 font-mono text-[13px] text-ink">{row.span}</td>
                                        <td className="py-2 pr-4 text-inkSoft">{row.p50.toFixed(1)}</td>
                                        <td className="py-2 pr-4 text-inkSoft">{row.p95.toFixed(1)}</td>
                                        <td className="py-2 text-inkSoft">{row.p99.toFixed(1)}</td>
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
