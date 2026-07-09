"use client";

import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { Button, Card, EmptyState, Pill } from "@/components/ui/primitives";

type RawUser = {
    id: string;
    username: string;
    email: string | null;
    department_id: string | null;
    is_active: boolean;
    mfa_enabled: boolean;
};

export function UsersTab() {
    const { data, loading, reload } = useApi<RawUser[]>("/admin/users");
    const [draft, setDraft] = useState({ username: "", email: "", password: "" });

    async function createUser() {
        await fetch("/api/v1/admin/users", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: draft.username, email: draft.email || null, password: draft.password || null }),
        });
        setDraft({ username: "", email: "", password: "" });
        reload();
    }

    async function toggleUser(user: RawUser) {
        await fetch(`/api/v1/admin/users/${user.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_active: !user.is_active }),
        });
        reload();
    }

    return (
        <div className="space-y-4">
            <Card className="p-5">
                <div className="grid gap-3 md:grid-cols-3">
                    <input value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} placeholder="Username" className="rounded-md border border-line bg-canvas px-3 py-2 text-sm" />
                    <input value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} placeholder="Email (optional)" className="rounded-md border border-line bg-canvas px-3 py-2 text-sm" />
                    <input value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} placeholder="Password (optional)" className="rounded-md border border-line bg-canvas px-3 py-2 text-sm" />
                </div>
                <div className="mt-4">
                    <Button onClick={createUser} disabled={!draft.username}>Add user</Button>
                </div>
            </Card>

            {loading ? <p className="text-sm text-inkFaint">Loading users…</p> : null}
            {!loading && !(data ?? []).length ? <EmptyState title="No users" hint="Create the first additional account here." /> : null}

            <div className="space-y-3">
                {(data ?? []).map((user) => (
                    <Card key={user.id} className="p-4">
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <div className="flex items-center gap-2">
                                    <div className="font-medium text-ink">{user.username}</div>
                                    <Pill tone={user.is_active ? "online" : "neutral"}>{user.is_active ? "active" : "inactive"}</Pill>
                                    {user.mfa_enabled ? <Pill tone="accent">mfa</Pill> : null}
                                </div>
                                <div className="mt-1 text-[12px] text-inkSoft">{user.email ?? "No email"}</div>
                            </div>
                            <Button variant="outline" onClick={() => toggleUser(user)}>{user.is_active ? "Deactivate" : "Activate"}</Button>
                        </div>
                    </Card>
                ))}
            </div>
        </div>
    );
}