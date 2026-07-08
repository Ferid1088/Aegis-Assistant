"use client";

import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import type { DocumentSourceConfig } from "@/types";
import { Button, Card, EmptyState, Pill } from "@/components/ui/primitives";
import { formatDate } from "@/lib/utils";

type RawSource = {
    id: string;
    name: string;
    kind: string;
    enabled: boolean;
    location: string;
    path_mapping: string | null;
    last_scan: string | null;
    status: string;
};

function toSource(raw: RawSource): DocumentSourceConfig {
    return {
        id: raw.id,
        name: raw.name,
        kind: raw.kind as DocumentSourceConfig["kind"],
        enabled: raw.enabled,
        location: raw.location,
        pathMapping: raw.path_mapping,
        lastScan: raw.last_scan,
        status: raw.status as DocumentSourceConfig["status"],
    };
}

export function SourcesTab() {
    const { data, loading, reload } = useApi<RawSource[]>("/admin/sources");
    const [draft, setDraft] = useState({ name: "", kind: "filesystem", location: "", pathMapping: "" });
    const sources = (data ?? []).map(toSource);

    async function createSource() {
        await fetch("/api/v1/admin/sources", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: draft.name,
                kind: draft.kind,
                location: draft.location,
                path_mapping: draft.pathMapping || null,
            }),
        });
        setDraft({ name: "", kind: "filesystem", location: "", pathMapping: "" });
        reload();
    }

    async function toggleSource(source: DocumentSourceConfig) {
        await fetch(`/api/v1/admin/sources/${source.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: !source.enabled }),
        });
        reload();
    }

    return (
        <div className="space-y-4">
            <Card className="p-5">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Source name" className="rounded-md border border-line bg-canvas px-3 py-2 text-sm" />
                    <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })} className="rounded-md border border-line bg-canvas px-3 py-2 text-sm">
                        <option value="filesystem">Filesystem</option>
                        <option value="s3">S3</option>
                        <option value="sql">SQL</option>
                        <option value="sqlite">SQLite</option>
                        <option value="api">HTTP API</option>
                        <option value="sharepoint">SharePoint</option>
                    </select>
                    <input value={draft.location} onChange={(e) => setDraft({ ...draft, location: e.target.value })} placeholder="Location" className="rounded-md border border-line bg-canvas px-3 py-2 text-sm" />
                    <input value={draft.pathMapping} onChange={(e) => setDraft({ ...draft, pathMapping: e.target.value })} placeholder="Path mapping (optional)" className="rounded-md border border-line bg-canvas px-3 py-2 text-sm" />
                </div>
                <div className="mt-4">
                    <Button onClick={createSource} disabled={!draft.name || !draft.location}>Add source</Button>
                </div>
            </Card>

            {loading ? <p className="text-sm text-inkFaint">Loading sources…</p> : null}

            {!loading && !sources.length ? (
                <EmptyState title="No sources configured" hint="Manual uploads still work, but you can also register watched sources here." />
            ) : null}

            <div className="space-y-3">
                {sources.map((source) => (
                    <Card key={source.id} className="p-4">
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <div className="flex items-center gap-2">
                                    <h3 className="font-medium text-ink">{source.name}</h3>
                                    <Pill>{source.kind}</Pill>
                                    <Pill tone={source.enabled ? "online" : "neutral"}>{source.enabled ? "enabled" : "disabled"}</Pill>
                                </div>
                                <p className="mt-1 font-mono text-[12px] text-inkFaint">{source.location}</p>
                                <p className="mt-1 text-[12px] text-inkSoft">Last scan: {formatDate(source.lastScan)}</p>
                            </div>
                            <Button variant="outline" onClick={() => toggleSource(source)}>
                                {source.enabled ? "Disable" : "Enable"}
                            </Button>
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
}