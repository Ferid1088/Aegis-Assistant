"use client";

import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Button, Card, EmptyState } from "@/components/ui/primitives";

type RegistryItem = { id: string; name?: string; label?: string };

export function RegistryTab({
    title,
    endpoint,
    bodyKey,
}: {
    title: string;
    endpoint: string;
    bodyKey: "name" | "label";
}) {
    const { data, loading, reload } = useApi<RegistryItem[]>(`/admin/${endpoint}`);
    const [draft, setDraft] = useState("");

    async function addItem() {
        await fetch(`/api/v1/admin/${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ [bodyKey]: draft }),
        });
        setDraft("");
        reload();
    }

    const items = data ?? [];

    return (
        <Card className="p-5">
            <div className="mb-4 flex gap-2">
                <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={`New ${title.toLowerCase()}…`} className="flex-1 rounded-md border border-line bg-canvas px-3 py-2 text-sm" />
                <Button onClick={addItem} disabled={!draft.trim()}>Add</Button>
            </div>
            {loading ? <p className="text-sm text-inkFaint">Loading {title.toLowerCase()}…</p> : null}
            {!loading && !items.length ? <EmptyState title={`No ${title.toLowerCase()} yet`} /> : null}
            <div className="space-y-2">
                {items.map((item) => (
                    <div key={item.id} className="rounded-md border border-line/70 px-3 py-2 text-sm text-ink">
                        {item.name ?? item.label ?? item.id}
                    </div>
                ))}
            </div>
        </Card>
    );
}