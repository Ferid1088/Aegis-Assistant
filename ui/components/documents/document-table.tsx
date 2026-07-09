"use client";

import Link from "next/link";
import type { LogicalDocument } from "@/types";
import { EmptyState, Pill } from "@/components/ui/primitives";
import { formatDate } from "@/lib/utils";

export function DocumentTable({ documents }: { documents: LogicalDocument[] }) {
    if (!documents.length) {
        return <EmptyState title="No documents yet" hint="Upload a PDF or add a watched source to populate the library." />;
    }

    return (
        <div className="overflow-hidden rounded-card border border-line bg-surface">
            <table className="w-full text-sm">
                <thead>
                    <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-inkFaint">
                        <th className="px-4 py-3">Title</th>
                        <th className="px-4 py-3">Department</th>
                        <th className="px-4 py-3">Type</th>
                        <th className="px-4 py-3">Versions</th>
                        <th className="px-4 py-3">Uploaded</th>
                        <th className="px-4 py-3">State</th>
                        <th className="px-4 py-3">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {documents.map((doc) => (
                        <tr key={doc.id} className="border-b border-line/60 last:border-0 hover:bg-surfaceMuted/40">
                            <td className="px-4 py-3 font-medium text-ink">
                                <Link href={`/viewer/${doc.id}`} className="hover:text-accent">
                                    {doc.title}
                                </Link>
                            </td>
                            <td className="px-4 py-3 text-inkSoft">{doc.department ?? "—"}</td>
                            <td className="px-4 py-3 text-inkSoft">{doc.documentType ?? "—"}</td>
                            <td className="px-4 py-3 font-mono text-[12px] text-inkSoft">
                                v{doc.activeVersionNo} · {doc.versionCount} total
                            </td>
                            <td className="px-4 py-3 text-inkSoft">{formatDate(doc.uploadDate)}</td>
                            <td className="px-4 py-3">
                                <Pill tone={doc.state === "active" ? "online" : "neutral"}>{doc.state}</Pill>
                            </td>
                            <td className="px-4 py-3">
                                <div className="flex gap-3 text-[12px] font-medium">
                                    <Link href={`/documents/${doc.id}`} className="text-accent hover:underline">Manage</Link>
                                    <Link href={`/viewer/${doc.id}`} className="text-inkSoft hover:text-ink">View</Link>
                                </div>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}