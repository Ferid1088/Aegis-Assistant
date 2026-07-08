"use client";

import { useApi } from "@/hooks/use-api";

type Department = { id: string; name: string };
type DocumentTypeOption = { id: string; label: string };
type AccessLevelOption = { id: string; label: string; rank: number };

export type DocumentMetadataValue = {
    department: string;
    documentType: string;
    accessLevel: string[];
};

export function DocumentMetadataFields({
    value,
    onChange,
    disabled,
}: {
    value: DocumentMetadataValue;
    onChange: (value: DocumentMetadataValue) => void;
    disabled: boolean;
}) {
    const { data: departments } = useApi<Department[]>("/admin/departments");
    const { data: documentTypes } = useApi<DocumentTypeOption[]>("/admin/document-types");
    const selectedDept = (departments ?? []).find((d) => d.name === value.department) ?? null;
    const { data: accessLevels } = useApi<AccessLevelOption[]>(
        selectedDept ? `/admin/departments/${selectedDept.id}/access-levels` : null,
    );

    return (
        <div className="grid gap-4 md:grid-cols-3">
            <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
                Department
                <select
                    value={value.department}
                    disabled={disabled}
                    onChange={(e) => onChange({ department: e.target.value, documentType: value.documentType, accessLevel: [] })}
                    className="rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink disabled:opacity-50"
                >
                    <option value="">— none —</option>
                    {(departments ?? []).map((d) => (
                        <option key={d.id} value={d.name}>{d.name}</option>
                    ))}
                </select>
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
                Document type
                <select
                    value={value.documentType}
                    disabled={disabled}
                    onChange={(e) => onChange({ ...value, documentType: e.target.value })}
                    className="rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink disabled:opacity-50"
                >
                    <option value="">— none —</option>
                    {(documentTypes ?? []).map((t) => (
                        <option key={t.id} value={t.label}>{t.label}</option>
                    ))}
                </select>
            </label>
            <div className="flex flex-col gap-1 text-[12px] text-inkSoft">
                Access level
                <select
                    multiple
                    value={value.accessLevel}
                    disabled={disabled || !selectedDept}
                    onChange={(e) => {
                        const selected = Array.from(e.target.selectedOptions, (o) => o.value);
                        onChange({ ...value, accessLevel: selected });
                    }}
                    className="min-h-[72px] rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink disabled:opacity-50"
                >
                    {(accessLevels ?? []).map((lvl) => (
                        <option key={lvl.id} value={lvl.label}>{lvl.label}</option>
                    ))}
                </select>
            </div>
        </div>
    );
}
