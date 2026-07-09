"use client";

import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { Button, Card, EmptyState, PageTitle, Pill } from "@/components/ui/primitives";

type RawAuditEntry = {
    actor_user: string;
    actor_username: string | null;
    action: string;
    resource: string;
    ts: string;
    request_id: string;
    prev_value: Record<string, unknown> | null;
    new_value: Record<string, unknown> | null;
};

type VerifyResult = { valid: boolean; count: number; error: string };

export function AuditView() {
    const { data, loading } = useApi<RawAuditEntry[]>("/admin/audit");
    const [verify, setVerify] = useState<VerifyResult | null>(null);
    const [verifying, setVerifying] = useState(false);
    const entries = data ?? [];

    async function runVerify() {
        setVerifying(true);
        try {
            setVerify(await api.get<VerifyResult>("/admin/audit/verify"));
        } finally {
            setVerifying(false);
        }
    }

    return (
        <div className="mx-auto max-w-6xl p-6">
            <PageTitle sub="Append-only, hash-chained log of every RBAC/user/document admin mutation.">Audit</PageTitle>

            <Card className="mb-6 flex items-center justify-between p-5">
                <div className="text-sm text-inkSoft">
                    {verify ? (
                        <span className="flex items-center gap-2">
                            <Pill tone={verify.valid ? "online" : "offline"}>{verify.valid ? "Chain intact" : "Chain broken"}</Pill>
                            {verify.count} entries verified
                            {verify.error ? <span className="text-offline"> — {verify.error}</span> : null}
                        </span>
                    ) : (
                        "Verify the hash chain hasn't been tampered with."
                    )}
                </div>
                <Button onClick={runVerify} disabled={verifying}>{verifying ? "Verifying…" : "Verify chain"}</Button>
            </Card>

            <Card className="p-5">
                {loading ? <p className="text-sm text-inkFaint">Loading…</p> : null}
                {!loading && !entries.length ? <EmptyState title="No audit entries yet" /> : null}
                {entries.length ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm">
                            <thead>
                                <tr className="text-[11px] uppercase tracking-wider text-inkFaint">
                                    <th className="pb-2 pr-4 font-medium">When</th>
                                    <th className="pb-2 pr-4 font-medium">Actor</th>
                                    <th className="pb-2 pr-4 font-medium">Action</th>
                                    <th className="pb-2 font-medium">Resource</th>
                                </tr>
                            </thead>
                            <tbody>
                                {entries.map((e) => (
                                    <tr key={e.request_id} className="border-t border-line/70">
                                        <td className="py-2 pr-4 text-inkFaint">{new Date(e.ts).toLocaleString()}</td>
                                        <td className="py-2 pr-4 text-ink">
                                            {e.actor_username ? (
                                                <span className={e.actor_username === "(deleted user)" ? "italic text-inkFaint" : undefined}>
                                                    {e.actor_username}
                                                </span>
                                            ) : (
                                                <span className="font-mono text-[12px] text-inkFaint">{e.actor_user}</span>
                                            )}
                                        </td>
                                        <td className="py-2 pr-4 text-ink">{e.action}</td>
                                        <td className="py-2 font-mono text-[12px] text-inkSoft">{e.resource}</td>
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
