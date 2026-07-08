"use client";

import { useState } from "react";
import type { LogicalDocument } from "@/types";
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
    const [pending, setPending] = useState(false);
    const [status, setStatus] = useState<string | null>(null);

    async function submit() {
        if (!file) return;
        setPending(true);
        setStatus(null);
        try {
            const form = new FormData();
            form.append("file", file);
            if (logicalDocId) form.append("logical_doc_id", logicalDocId);
            const res = await fetch("/api/v1/documents", { method: "POST", body: form });
            if (!res.ok) {
                const detail = await res.text();
                setStatus(detail || "Upload failed");
                return;
            }
            setStatus("Queued for processing.");
            setFile(null);
            setLogicalDocId(defaultLogicalDocId ?? "");
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
            <div className="mt-4 flex items-center gap-3">
                <Button onClick={submit} disabled={!file || pending}>{pending ? "Uploading…" : "Upload"}</Button>
                {status ? <span className="text-[12px] text-inkSoft">{status}</span> : null}
            </div>
        </Card>
    );
}