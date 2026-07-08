"use client";

import { useApi } from "@/hooks/use-api";
import type { QuarantineItem } from "@/types";
import { Card, EmptyState, Pill } from "@/components/ui/primitives";
import { formatDate } from "@/lib/utils";

type RawQuarantine = {
    id: string;
    document_title: string;
    reason: string;
    stage: string;
    quarantined_at: string;
};

function toItem(raw: RawQuarantine): QuarantineItem {
    return {
        id: raw.id,
        documentTitle: raw.document_title,
        reason: raw.reason,
        stage: raw.stage,
        quarantinedAt: raw.quarantined_at,
    };
}

export function QuarantineQueue() {
    const { data, loading } = useApi<RawQuarantine[]>("/admin/quarantine");
    const items = (data ?? []).map(toItem);

    if (loading) return <p className="text-sm text-inkFaint">Loading quarantine…</p>;
    if (!items.length) return <EmptyState title="Nothing is quarantined" hint="Documents that require manual review will appear here." />;

    return (
        <div className="space-y-3">
            {items.map((item) => (
                <Card key={item.id} className="p-4">
                    <div className="flex items-start justify-between gap-4">
                        <div>
                            <div className="font-medium text-ink">{item.documentTitle}</div>
                            <div className="mt-1 text-[12px] text-inkSoft">{item.reason} · {formatDate(item.quarantinedAt)}</div>
                        </div>
                        <Pill tone="offline">{item.stage}</Pill>
                    </div>
                </Card>
            ))}
        </div>
    );
}