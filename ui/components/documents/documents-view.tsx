"use client";

import { useMemo, useState } from "react";
import type { LogicalDocument } from "@/types";
import { useApi } from "@/hooks/use-api";
import { PageTitle, Button } from "@/components/ui/primitives";
import { DocumentTable } from "./document-table";
import { UploadPanel } from "./upload-panel";
import { SourcesTab } from "@/components/sources/sources-tab";
import { IngestionQueue } from "@/components/sources/ingestion-queue";
import { QuarantineQueue } from "@/components/sources/quarantine-queue";

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

const TABS = ["library", "sources", "ingestion", "quarantine"] as const;
type Tab = (typeof TABS)[number];

export function DocumentsView() {
    const [tab, setTab] = useState<Tab>("library");
    const [showUpload, setShowUpload] = useState(false);
    const { data, loading, reload } = useApi<RawDocument[]>("/documents");
    const documents = useMemo(() => (data ?? []).map(toDocument), [data]);

    return (
        <div className="mx-auto max-w-6xl p-6">
            <div className="flex items-start justify-between gap-4">
                <PageTitle sub="Library, watched sources, queue state, and quarantine review.">Documents</PageTitle>
                {tab === "library" ? <Button onClick={() => setShowUpload((value) => !value)}>{showUpload ? "Hide upload" : "Upload PDF"}</Button> : null}
            </div>

            <div className="mb-6 flex gap-1 border-b border-line">
                {TABS.map((item) => (
                    <button
                        key={item}
                        onClick={() => setTab(item)}
                        className={`border-b-2 px-3 py-2 text-sm ${tab === item ? "border-accent text-ink" : "border-transparent text-inkSoft"}`}
                    >
                        {item[0].toUpperCase() + item.slice(1)}
                    </button>
                ))}
            </div>

            {tab === "library" ? (
                <>
                    {showUpload ? <UploadPanel onDone={reload} documents={documents} /> : null}
                    {loading ? <p className="text-sm text-inkFaint">Loading documents…</p> : <DocumentTable documents={documents} />}
                </>
            ) : null}

            {tab === "sources" ? <SourcesTab /> : null}
            {tab === "ingestion" ? <IngestionQueue /> : null}
            {tab === "quarantine" ? <QuarantineQueue /> : null}
        </div>
    );
}