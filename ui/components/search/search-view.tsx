"use client";

import { useMemo, useState } from "react";
import type { Facet, LogicalDocument, SearchHit } from "@/types";
import { Button, EmptyState, PageTitle, Pill } from "@/components/ui/primitives";
import { ResultCard } from "./result-card";

type RawDocument = {
    id: string;
    title: string;
    department: string | null;
    access_level: string | null;
    document_type: string | null;
    project: string | null;
    phase: string | null;
    upload_date: string;
    last_modified: string | null;
    active_version_no: number;
    version_count: number;
    file_type: string;
    state: string;
};

type RawSearchHit = {
    document: RawDocument;
    snippet: string;
    relevance: number;
    jump_to?: { page: number; region?: [number, number, number, number] };
};

type RawFacet = { field: string; label: string; values: { value: string; count: number }[] };

function toDocument(raw: RawDocument): LogicalDocument {
    return {
        id: raw.id,
        title: raw.title,
        department: raw.department,
        accessLevel: raw.access_level,
        documentType: raw.document_type,
        project: raw.project,
        phase: raw.phase,
        uploadDate: raw.upload_date,
        lastModified: raw.last_modified,
        activeVersionNo: raw.active_version_no,
        versionCount: raw.version_count,
        fileType: raw.file_type,
    };
}

export function SearchView() {
    const [query, setQuery] = useState("");
    const [mode, setMode] = useState<"documents" | "deep">("deep");
    const [hits, setHits] = useState<SearchHit[]>([]);
    const [facets, setFacets] = useState<Facet[]>([]);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [searched, setSearched] = useState(false);

    async function run() {
        if (!query.trim()) return;
        setLoading(true);
        setSearched(true);
        try {
            const res = await fetch("/api/v1/search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query, mode }),
            });
            const data = (await res.json()) as { hits: RawSearchHit[]; facets: RawFacet[] };
            const mappedHits = (data.hits ?? []).map((hit) => ({
                document: toDocument(hit.document),
                snippet: hit.snippet,
                relevance: hit.relevance,
                jumpTo: hit.jump_to,
            }));
            setHits(mappedHits);
            setFacets((data.facets ?? []).map((facet) => ({ field: facet.field, label: facet.label, values: facet.values })));
            setSelectedId(mappedHits[0]?.document.id ?? null);
        } finally {
            setLoading(false);
        }
    }

    const selected = useMemo(() => hits.find((hit) => hit.document.id === selectedId)?.document ?? null, [hits, selectedId]);

    return (
        <div className="flex h-full">
            <aside className="w-80 shrink-0 border-r border-line bg-surface p-5">
                <PageTitle sub="Search across indexed documents without generating a full answer.">Search</PageTitle>
                <div className="space-y-3">
                    <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} placeholder="Find a policy, contract, or manual…" className="w-full rounded-md border border-line bg-canvas px-3 py-2 text-sm" />
                    <div className="flex gap-2">
                        <Button variant={mode === "documents" ? "solid" : "outline"} onClick={() => setMode("documents")}>Documents</Button>
                        <Button variant={mode === "deep" ? "solid" : "outline"} onClick={() => setMode("deep")}>Deep</Button>
                    </div>
                    <Button onClick={run} disabled={!query.trim() || loading}>{loading ? "Searching…" : "Search"}</Button>
                </div>
                <div className="mt-6 space-y-3">
                    {facets.map((facet) => (
                        <div key={facet.field}>
                            <div className="mb-2 text-[11px] uppercase tracking-wider text-inkFaint">{facet.label}</div>
                            <div className="flex flex-wrap gap-2">
                                {facet.values.map((value) => (
                                    <Pill key={value.value}>{value.value} · {value.count}</Pill>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            </aside>

            <div className="min-w-0 flex-1 overflow-y-auto p-6">
                {!searched ? <EmptyState title="Find a document" hint="Describe what you need in plain language." /> : null}
                {searched && !loading && !hits.length ? <EmptyState title="No accessible documents match" hint="Try broader search terms." /> : null}
                <div className="space-y-4">
                    {hits.map((hit) => (
                        <ResultCard key={hit.document.id + String(hit.jumpTo?.page ?? 0)} hit={hit} active={selectedId === hit.document.id} onSelect={() => setSelectedId(hit.document.id)} />
                    ))}
                </div>
            </div>

            {selected ? (
                <aside className="hidden w-80 shrink-0 border-l border-line bg-surface p-5 lg:block">
                    <div className="text-[11px] uppercase tracking-wider text-inkFaint">Selected document</div>
                    <h2 className="mt-2 font-display text-lg text-ink">{selected.title}</h2>
                    <div className="mt-3 space-y-2 text-sm text-inkSoft">
                        <div>Department: {selected.department ?? "—"}</div>
                        <div>Type: {selected.documentType ?? "—"}</div>
                        <div>Project: {selected.project ?? "—"}</div>
                        <div>Versions: {selected.versionCount}</div>
                    </div>
                </aside>
            ) : null}
        </div>
    );
}