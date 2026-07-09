"use client";

import type { LogicalDocument } from "@/types";
import { Eyebrow, Pill } from "@/components/ui/primitives";
import { formatDate } from "@/lib/utils";

type Version = { versionId: string; versionNo: number; isActive: boolean; uploadedAt: string };

export function MetadataSidebar({ document, versions }: { document: LogicalDocument; versions: Version[] }) {
    return (
        <aside className="hidden w-72 shrink-0 overflow-y-auto border-l border-line bg-surface p-5 lg:block">
            <Eyebrow>Metadata</Eyebrow>
            <div className="mt-3 space-y-2 text-sm text-inkSoft">
                <div>Department: {document.department ?? "—"}</div>
                <div>Access: {document.accessLevel ?? "—"}</div>
                <div>Type: {document.documentType ?? "—"}</div>
                <div>Project: {document.project ?? "—"}</div>
                <div>Phase: {document.phase ?? "—"}</div>
                <div>Uploaded: {formatDate(document.uploadDate)}</div>
                <div>File type: {document.fileType}</div>
            </div>

            <div className="mt-6">
                <Eyebrow>Versions</Eyebrow>
                <div className="mt-3 space-y-2">
                    {versions.map((version) => (
                        <div key={version.versionId} className="flex items-center justify-between text-[12px]">
                            <span className={version.isActive ? "font-medium text-ink" : "text-inkSoft"}>
                                v{version.versionNo} · {formatDate(version.uploadedAt)}
                            </span>
                            {version.isActive ? <Pill tone="accent">active</Pill> : null}
                        </div>
                    ))}
                </div>
            </div>
        </aside>
    );
}