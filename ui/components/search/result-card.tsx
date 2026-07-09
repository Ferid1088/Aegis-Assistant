"use client";

import Link from "next/link";
import type { SearchHit } from "@/types";
import { Card, Pill } from "@/components/ui/primitives";

export function ResultCard({ hit, active, onSelect }: { hit: SearchHit; active: boolean; onSelect: () => void }) {
    const region = hit.jumpTo?.region ? `&region=${hit.jumpTo.region.join(",")}` : "";
    const href = `/viewer/${hit.document.id}?page=${hit.jumpTo?.page ?? 1}${region}`;

    return (
        <Card className={`p-4 ${active ? "border-accent" : ""}`}>
            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                    <button onClick={onSelect} className="text-left font-medium text-ink hover:text-accent">{hit.document.title}</button>
                    <div className="mt-1 flex flex-wrap gap-2 text-[12px] text-inkFaint">
                        {hit.document.department ? <Pill>{hit.document.department}</Pill> : null}
                        {hit.document.documentType ? <Pill tone="accent">{hit.document.documentType}</Pill> : null}
                    </div>
                    <p className="mt-3 text-sm text-inkSoft">{hit.snippet}</p>
                </div>
                <div className="shrink-0 text-right">
                    <div className="text-[12px] text-inkFaint">{Math.round(hit.relevance * 100)}%</div>
                    <Link href={href} className="mt-2 inline-block text-[12px] font-medium text-accent hover:underline">Open viewer</Link>
                </div>
            </div>
        </Card>
    );
}