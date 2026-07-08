"use client";

import { useEffect, useMemo, useState } from "react";
import type { AccessLevel, Department, DocumentType, LogicalDocument } from "@/types";
import { useApi } from "@/hooks/use-api";
import { Button, Card, EmptyState, PageTitle, Pill } from "@/components/ui/primitives";
import { UploadPanel } from "./upload-panel";
import { formatDate } from "@/lib/utils";

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
    department_id: string | null;
    access_level: string | null;
    access_level_ids: string[];
    document_type: string | null;
    document_type_id: string | null;
    project: string | null;
    phase: string | null;
    upload_date: string;
    last_modified: string | null;
    active_version_no: number;
    version_count: number;
    file_type: string;
    state: string;
    versions: RawVersion[];
    can_manage: boolean;
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

export function DocumentManageView({ docId }: { docId: string }) {
    const { data, loading, error, reload } = useApi<RawDocumentDetail>(`/documents/${docId}`);
    const [showUpload, setShowUpload] = useState(false);
    const [showEdit, setShowEdit] = useState(false);
    const document = useMemo(() => (data ? toDocument(data) : null), [data]);

    async function activate(versionId: string, versionNo: number) {
        await fetch(`/api/v1/documents/${docId}/versions/${versionId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ version_no: versionNo }),
        });
        reload();
    }

    if (loading) return <div className="p-6 text-sm text-inkFaint">Loading document…</div>;
    if (error || !data || !document) return <div className="p-6"><EmptyState title="Document not found" /></div>;

    return (
        <div className="mx-auto max-w-5xl p-6">
            <div className="flex items-start justify-between gap-4">
                <PageTitle sub="Review metadata, inspect versions, and activate a different version.">{document.title}</PageTitle>
                <div className="flex gap-2">
                    {data.can_manage ? <Button onClick={() => setShowEdit((value) => !value)}>{showEdit ? "Hide edit metadata" : "Edit metadata"}</Button> : null}
                    {data.can_manage ? <Button onClick={() => setShowUpload((value) => !value)}>{showUpload ? "Hide version upload" : "Upload new version"}</Button> : null}
                </div>
            </div>

            {showEdit ? <EditMetadataForm docId={docId} detail={data} onDone={() => { setShowEdit(false); reload(); }} /> : null}
            {showUpload ? <UploadPanel onDone={reload} documents={[document]} defaultLogicalDocId={docId} /> : null}

            <Card className="mb-6 p-5">
                <div className="grid gap-3 md:grid-cols-3">
                    <MetaRow label="Department" value={document.department} />
                    <MetaRow label="Access level" value={document.accessLevel} />
                    <MetaRow label="Document type" value={document.documentType} />
                    <MetaRow label="Project" value={document.project} />
                    <MetaRow label="Phase" value={document.phase} />
                    <MetaRow label="Last modified" value={formatDate(document.lastModified)} />
                </div>
            </Card>

            <Card className="overflow-hidden">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-inkFaint">
                            <th className="px-4 py-3">Version</th>
                            <th className="px-4 py-3">Filename</th>
                            <th className="px-4 py-3">Pages</th>
                            <th className="px-4 py-3">Uploaded</th>
                            <th className="px-4 py-3">State</th>
                            <th className="px-4 py-3">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {data.versions.map((version) => (
                            <tr key={version.version_id} className="border-b border-line/60 last:border-0">
                                <td className="px-4 py-3 font-mono text-[12px] text-inkSoft">v{version.version_no}</td>
                                <td className="px-4 py-3 text-ink">{version.filename}</td>
                                <td className="px-4 py-3 text-inkSoft">{version.num_pages ?? "—"}</td>
                                <td className="px-4 py-3 text-inkSoft">{formatDate(version.uploaded_at)}</td>
                                <td className="px-4 py-3">
                                    <Pill tone={version.is_active ? "online" : "neutral"}>{version.processing_state}</Pill>
                                </td>
                                <td className="px-4 py-3">
                                    {version.is_active ? (
                                        <span className="text-[12px] text-inkFaint">Active</span>
                                    ) : data.can_manage ? (
                                        <Button variant="outline" onClick={() => activate(version.version_id, version.version_no)}>Activate</Button>
                                    ) : (
                                        <span className="text-[12px] text-inkFaint">Read only</span>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </Card>
        </div>
    );
}

function EditMetadataForm({ docId, detail, onDone }: { docId: string; detail: RawDocumentDetail; onDone: () => void }) {
    const [title, setTitle] = useState(detail.title);
    const [departmentId, setDepartmentId] = useState(detail.department_id ?? "");
    const [documentTypeId, setDocumentTypeId] = useState(detail.document_type_id ?? "");
    const [accessLevelIds, setAccessLevelIds] = useState<string[]>(detail.access_level_ids ?? []);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const { data: departments } = useApi<Department[]>("/admin/departments");
    const { data: documentTypes } = useApi<DocumentType[]>("/admin/document-types");
    const { data: accessLevels } = useApi<AccessLevel[]>(
        departmentId ? `/admin/departments/${departmentId}/access-levels` : null
    );

    useEffect(() => {
        if (departmentId !== (detail.department_id ?? "")) {
            setAccessLevelIds([]);
        }
        // Only reset when the department actually changes away from the document's
        // current one -- otherwise the initial pre-filled selection would be wiped
        // by this same effect running on mount.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [departmentId]);

    function toggleAccessLevel(id: string) {
        setAccessLevelIds((current) =>
            current.includes(id) ? current.filter((existing) => existing !== id) : [...current, id]
        );
    }

    async function submit() {
        setPending(true);
        setError(null);
        try {
            const res = await fetch(`/api/v1/documents/${docId}/metadata`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title, department_id: departmentId, document_type_id: documentTypeId,
                    access_level_ids: accessLevelIds,
                }),
            });
            if (!res.ok) {
                const detail = await res.text();
                setError(detail || "Failed to save metadata.");
                return;
            }
            onDone();
        } catch {
            setError("Failed to save metadata.");
        } finally {
            setPending(false);
        }
    }

    return (
        <Card className="mb-6 p-5">
            <div className="grid gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
                    Title
                    <input
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        className="rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink"
                    />
                </label>
                <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
                    Department
                    <select
                        value={departmentId}
                        onChange={(e) => setDepartmentId(e.target.value)}
                        className="rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink"
                    >
                        <option value="">Select a department…</option>
                        {(departments ?? []).map((dept) => (
                            <option key={dept.id} value={dept.id}>{dept.name}</option>
                        ))}
                    </select>
                </label>
                <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
                    Document type
                    <select
                        value={documentTypeId}
                        onChange={(e) => setDocumentTypeId(e.target.value)}
                        className="rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink"
                    >
                        <option value="">Select a document type…</option>
                        {(documentTypes ?? []).map((dtype) => (
                            <option key={dtype.id} value={dtype.id}>{dtype.label}</option>
                        ))}
                    </select>
                </label>
                <div className="flex flex-col gap-1 text-[12px] text-inkSoft">
                    Access level
                    <div className="flex flex-col gap-1 rounded-md border border-line bg-canvas px-3 py-2">
                        {(accessLevels ?? []).map((level) => (
                            <label key={level.id} className="flex items-center gap-2 text-sm text-ink">
                                <input
                                    type="checkbox"
                                    checked={accessLevelIds.includes(level.id)}
                                    onChange={() => toggleAccessLevel(level.id)}
                                />
                                {level.label}
                            </label>
                        ))}
                    </div>
                </div>
            </div>
            <div className="mt-4 flex items-center gap-3">
                <Button onClick={submit} disabled={pending || !title.trim() || !departmentId || !documentTypeId || accessLevelIds.length === 0}>
                    {pending ? "Saving…" : "Save metadata"}
                </Button>
                {error ? <span className="text-sm text-offline">{error}</span> : null}
            </div>
        </Card>
    );
}

function MetaRow({ label, value }: { label: string; value: string | null }) {
    return (
        <div>
            <div className="text-[11px] uppercase tracking-wider text-inkFaint">{label}</div>
            <div className="mt-1 text-sm text-ink">{value || "—"}</div>
        </div>
    );
}
