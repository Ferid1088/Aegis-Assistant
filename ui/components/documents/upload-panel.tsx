"use client";

import { useEffect, useState } from "react";
import type { AccessLevel, Department, DocumentType, LogicalDocument } from "@/types";
import { useApi } from "@/hooks/use-api";
import { Button, Card } from "@/components/ui/primitives";

export function UploadPanel({
    onDone,
    documents,
    defaultLogicalDocId,
}: {
    onDone: () => void;
    documents: LogicalDocument[];
    defaultLogicalDocId?: string;
}) {
    const [file, setFile] = useState<File | null>(null);
    const [logicalDocId, setLogicalDocId] = useState(defaultLogicalDocId ?? "");
    const [title, setTitle] = useState("");
    const [departmentId, setDepartmentId] = useState("");
    const [documentTypeId, setDocumentTypeId] = useState("");
    const [accessLevelIds, setAccessLevelIds] = useState<string[]>([]);
    const [pending, setPending] = useState(false);
    const [status, setStatus] = useState<string | null>(null);

    const isNewVersionUpload = Boolean(logicalDocId);

    const { data: departments } = useApi<Department[]>("/admin/departments");
    const { data: documentTypes } = useApi<DocumentType[]>("/admin/document-types");
    const { data: accessLevels } = useApi<AccessLevel[]>(
        departmentId ? `/admin/departments/${departmentId}/access-levels` : null
    );

    useEffect(() => {
        setAccessLevelIds([]);
    }, [departmentId]);

    function toggleAccessLevel(id: string) {
        setAccessLevelIds((current) =>
            current.includes(id) ? current.filter((existing) => existing !== id) : [...current, id]
        );
    }

    const metadataComplete = isNewVersionUpload || (title.trim() && departmentId && documentTypeId && accessLevelIds.length > 0);

    async function submit() {
        if (!file || !metadataComplete) return;
        setPending(true);
        setStatus(null);
        try {
            const form = new FormData();
            form.append("file", file);
            if (logicalDocId) {
                form.append("logical_doc_id", logicalDocId);
            } else {
                form.append("title", title);
                form.append("department_id", departmentId);
                form.append("document_type_id", documentTypeId);
                accessLevelIds.forEach((id) => form.append("access_level_ids", id));
            }
            const res = await fetch("/api/v1/documents", { method: "POST", body: form });
            if (!res.ok) {
                const detail = await res.text();
                setStatus(detail || "Upload failed");
                return;
            }
            setStatus("Queued for processing.");
            setFile(null);
            setLogicalDocId(defaultLogicalDocId ?? "");
            setTitle("");
            setDepartmentId("");
            setDocumentTypeId("");
            setAccessLevelIds([]);
            onDone();
        } catch {
            setStatus("Upload failed.");
        } finally {
            setPending(false);
        }
    }

    return (
        <Card className="mb-6 p-5">
            <div className="grid gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
                    PDF file
                    <input
                        type="file"
                        accept="application/pdf"
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                        className="rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink"
                    />
                </label>
                <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
                    Upload as new version of (optional)
                    <select
                        value={logicalDocId}
                        onChange={(e) => setLogicalDocId(e.target.value)}
                        className="rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink"
                    >
                        <option value="">Create a new logical document</option>
                        {documents.map((doc) => (
                            <option key={doc.id} value={doc.id}>
                                {doc.title}
                            </option>
                        ))}
                    </select>
                </label>
            </div>

            {!isNewVersionUpload && (
                <div className="mt-4 grid gap-4 md:grid-cols-2">
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
                            {!departmentId && <span className="text-inkFaint">Select a department first…</span>}
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
            )}

            <div className="mt-4 flex items-center gap-3">
                <Button onClick={submit} disabled={!file || !metadataComplete || pending}>
                    {pending ? "Uploading…" : "Upload"}
                </Button>
                {status ? <span className="text-[12px] text-inkSoft">{status}</span> : null}
            </div>
        </Card>
    );
}
