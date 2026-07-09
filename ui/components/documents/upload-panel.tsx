"use client";

import { useEffect, useState } from "react";
import type { AccessLevel, Department, DocumentType, LogicalDocument } from "@/types";
import { useApi } from "@/hooks/use-api";
import { api } from "@/lib/api";
import { Button, Card } from "@/components/ui/primitives";

interface JobStatus {
    job_id: string;
    status: string;
    error: string | null;
    logical_doc_id: string | null;
    indexed_count: number | null;
}

const JOB_POLL_INTERVAL_MS = 2000;
const JOB_POLL_MAX_ATTEMPTS = 150; // ~5 minutes, generous for a cold model-load ingestion run

async function pollJobUntilTerminal(jobId: string, onUpdate: (job: JobStatus) => void): Promise<void> {
    for (let attempt = 0; attempt < JOB_POLL_MAX_ATTEMPTS; attempt++) {
        let job: JobStatus;
        try {
            job = await api.get<JobStatus>(`/documents/jobs/${jobId}`);
        } catch {
            return; // job status is best-effort feedback; a transient fetch error shouldn't loop forever
        }
        if (job.status === "done" || job.status === "failed") {
            onUpdate(job);
            return;
        }
        await new Promise((resolve) => setTimeout(resolve, JOB_POLL_INTERVAL_MS));
    }
}

function describeJobOutcome(job: JobStatus): string {
    if (job.status === "failed") {
        return `Processing failed: ${job.error ?? "unknown error"}`;
    }
    if (job.indexed_count === null) {
        // convert() short-circuits on a content-hash match within the same department
        // without producing new chunks -- see rag/graphs/ingestion.py's dedup gate.
        return "This file's content already exists as a document in this department -- no new content was indexed.";
    }
    return `Indexed ${job.indexed_count} chunk${job.indexed_count === 1 ? "" : "s"}.`;
}

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
            const { job_id: jobId } = (await res.json()) as { job_id: string };
            setStatus("Queued for processing…");
            setFile(null);
            setLogicalDocId(defaultLogicalDocId ?? "");
            setTitle("");
            setDepartmentId("");
            setDocumentTypeId("");
            setAccessLevelIds([]);
            onDone();
            pollJobUntilTerminal(jobId, (job) => {
                setStatus(describeJobOutcome(job));
                onDone();
            });
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
