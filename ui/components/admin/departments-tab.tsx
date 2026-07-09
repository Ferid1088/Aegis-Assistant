"use client";

import { useState } from "react";
import type { Department } from "@/types";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { Button, Card, EmptyState } from "@/components/ui/primitives";

type AccessLevelItem = { id: string; department_id: string; label: string; rank: number };

function AccessLevelsSection({ departmentId }: { departmentId: string }) {
    const { data, loading, reload } = useApi<AccessLevelItem[]>(`/admin/departments/${departmentId}/access-levels`);
    const [label, setLabel] = useState("");
    const [rank, setRank] = useState("1");
    const levels = data ?? [];

    async function addLevel() {
        if (!label.trim()) return;
        await api.post(`/admin/departments/${departmentId}/access-levels`, { label, rank: Number(rank) || 0 });
        setLabel("");
        setRank("1");
        reload();
    }

    async function removeLevel(id: string) {
        await api.delete(`/admin/access-levels/${id}`);
        reload();
    }

    return (
        <div className="mt-3 border-t border-line/70 pt-3">
            <p className="mb-2 text-[12px] uppercase tracking-wide text-inkFaint">Access levels</p>
            {loading ? <p className="text-sm text-inkFaint">Loading…</p> : null}
            {!loading && !levels.length ? (
                <p className="mb-2 text-[12px] text-inkFaint">
                    None yet — documents in this department can&apos;t be uploaded until at least one exists.
                </p>
            ) : null}
            <div className="mb-2 space-y-1">
                {levels
                    .slice()
                    .sort((a, b) => a.rank - b.rank)
                    .map((level) => (
                        <div key={level.id} className="flex items-center justify-between rounded-md border border-line/70 px-3 py-1.5 text-sm text-ink">
                            <span>{level.label} <span className="text-inkFaint">(rank {level.rank})</span></span>
                            <Button variant="danger" onClick={() => removeLevel(level.id)}>Remove</Button>
                        </div>
                    ))}
            </div>
            <div className="flex gap-2">
                <input
                    value={label}
                    onChange={(e) => setLabel(e.target.value)}
                    placeholder="New access level (e.g. General)…"
                    className="flex-1 rounded-md border border-line bg-canvas px-3 py-2 text-sm"
                />
                <input
                    value={rank}
                    onChange={(e) => setRank(e.target.value)}
                    type="number"
                    placeholder="Rank"
                    className="w-20 rounded-md border border-line bg-canvas px-3 py-2 text-sm"
                />
                <Button onClick={addLevel} disabled={!label.trim()}>Add</Button>
            </div>
        </div>
    );
}

export function DepartmentsTab() {
    const { data, loading, reload } = useApi<Department[]>("/admin/departments");
    const [draft, setDraft] = useState("");
    const departments = data ?? [];

    async function addDepartment() {
        if (!draft.trim()) return;
        await api.post("/admin/departments", { name: draft });
        setDraft("");
        reload();
    }

    async function removeDepartment(id: string) {
        await api.delete(`/admin/departments/${id}`);
        reload();
    }

    return (
        <Card className="p-5">
            <div className="mb-4 flex gap-2">
                <input
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="New department…"
                    className="flex-1 rounded-md border border-line bg-canvas px-3 py-2 text-sm"
                />
                <Button onClick={addDepartment} disabled={!draft.trim()}>Add</Button>
            </div>
            {loading ? <p className="text-sm text-inkFaint">Loading departments…</p> : null}
            {!loading && !departments.length ? <EmptyState title="No departments yet" /> : null}
            <div className="space-y-4">
                {departments.map((dept) => (
                    <div key={dept.id} className="rounded-md border border-line/70 p-3">
                        <div className="flex items-center justify-between">
                            <span className="text-sm font-medium text-ink">{dept.name}</span>
                            <Button variant="danger" onClick={() => removeDepartment(dept.id)}>Remove</Button>
                        </div>
                        <AccessLevelsSection departmentId={dept.id} />
                    </div>
                ))}
            </div>
        </Card>
    );
}
