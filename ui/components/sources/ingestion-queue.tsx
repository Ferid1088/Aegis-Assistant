"use client";

import { useApi } from "@/hooks/use-api";
import type { IngestionJob } from "@/types";
import { Card, EmptyState, Pill } from "@/components/ui/primitives";
import { formatDate } from "@/lib/utils";

type RawJob = {
    id: string;
    document_title: string;
    state: string;
    progress: number;
    source_name: string;
    started_at: string;
    error: string | null;
};

function toJob(raw: RawJob): IngestionJob {
    return {
        id: raw.id,
        documentTitle: raw.document_title,
        state: raw.state as IngestionJob["state"],
        progress: raw.progress,
        sourceName: raw.source_name,
        startedAt: raw.started_at,
        error: raw.error,
    };
}

export function IngestionQueue() {
    const { data, loading } = useApi<RawJob[]>("/admin/ingestion/jobs");
    const jobs = (data ?? []).map(toJob);

    if (loading) return <p className="text-sm text-inkFaint">Loading ingestion jobs…</p>;
    if (!jobs.length) return <EmptyState title="No ingestion jobs" hint="Queued and completed uploads will appear here." />;

    return (
        <div className="space-y-3">
            {jobs.map((job) => (
                <Card key={job.id} className="p-4">
                    <div className="flex items-start justify-between gap-4">
                        <div>
                            <div className="font-medium text-ink">{job.documentTitle}</div>
                            <div className="mt-1 text-[12px] text-inkSoft">{job.sourceName} · {formatDate(job.startedAt)}</div>
                            {job.error ? <div className="mt-1 text-[12px] text-offline">{job.error}</div> : null}
                        </div>
                        <Pill tone={job.state === "failed" ? "offline" : job.state === "active" ? "online" : "accent"}>{job.state}</Pill>
                    </div>
                </Card>
            ))}
        </div>
    );
}