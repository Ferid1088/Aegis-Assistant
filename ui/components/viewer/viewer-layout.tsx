"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { LogicalDocument } from "@/types";
import { useApi } from "@/hooks/use-api";
import { Button } from "@/components/ui/primitives";
import { PageCanvas } from "./page-canvas";
import { VersionSwitcher } from "./version-switcher";
import { MetadataSidebar } from "./metadata-sidebar";

type RawVersion = {
    version_id: string;
    version_no: number;
    filename: string;
    num_pages: number | null;
    is_active: boolean;
    processing_state: string;
    uploaded_at: string;
    file_type: string;
};

type RawDocumentDetail = {
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
    versions: RawVersion[];
};

function toDocument(raw: RawDocumentDetail): LogicalDocument {
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

export function ViewerLayout({ docId, initialVersion, initialPage = 1, initialRegion }: { docId: string; initialVersion?: number; initialPage?: number; initialRegion?: [number, number, number, number] | null; }) {
    const { data, loading } = useApi<RawDocumentDetail>(`/documents/${docId}`);
    const [versionNo, setVersionNo] = useState<number | undefined>(initialVersion);
    const [page, setPage] = useState(initialPage);

    const document = useMemo(() => (data ? toDocument(data) : null), [data]);
    const versions = data?.versions ?? [];
    const effectiveVersionNo = versionNo ?? data?.active_version_no;
    const pageCount = versions.find((version) => version.version_no === effectiveVersionNo)?.num_pages ?? 1;

    if (loading || !data || !document) {
        return <div className="p-6 text-sm text-inkFaint">Loading viewer…</div>;
    }

    return (
        <div className="flex h-full">
            <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex items-center gap-3 border-b border-line bg-surface px-5 py-3">
                    <h1 className="min-w-0 flex-1 truncate font-display text-[16px] text-ink">{document.title}</h1>
                    <VersionSwitcher
                        versions={versions.map((version) => ({ versionId: version.version_id, versionNo: version.version_no, isActive: version.is_active }))}
                        current={effectiveVersionNo}
                        onChange={(nextVersion) => {
                            setVersionNo(nextVersion);
                            setPage(1);
                        }}
                    />
                    <div className="flex items-center gap-1 rounded-md border border-line px-1 py-0.5">
                        <button onClick={() => setPage((value) => Math.max(1, value - 1))} className="p-1 text-inkSoft hover:text-ink" aria-label="Previous page">
                            <ChevronLeft className="h-4 w-4" />
                        </button>
                        <span className="min-w-[64px] text-center font-mono text-[12px] text-inkSoft">{page} / {pageCount}</span>
                        <button onClick={() => setPage((value) => Math.min(pageCount, value + 1))} className="p-1 text-inkSoft hover:text-ink" aria-label="Next page">
                            <ChevronRight className="h-4 w-4" />
                        </button>
                    </div>
                    <Button variant="outline" onClick={() => window.history.back()}>Back</Button>
                </div>
                <div className="min-h-0 flex-1 overflow-auto bg-canvas p-6">
                    <PageCanvas docId={docId} versionNo={effectiveVersionNo} page={page} highlights={initialRegion && page === initialPage ? [initialRegion] : []} />
                </div>
            </div>
            <MetadataSidebar document={document} versions={versions.map((version) => ({ versionId: version.version_id, versionNo: version.version_no, isActive: version.is_active, uploadedAt: version.uploaded_at }))} />
        </div>
    );
}