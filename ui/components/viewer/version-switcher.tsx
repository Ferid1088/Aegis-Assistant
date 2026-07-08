"use client";

type Version = { versionId: string; versionNo: number; isActive: boolean };

export function VersionSwitcher({
    versions,
    current,
    onChange,
}: {
    versions: Version[];
    current?: number;
    onChange: (versionNo: number) => void;
}) {
    if (!versions.length) return null;
    return (
        <label className="flex items-center gap-2 text-[12px] text-inkFaint">
            Version
            <select value={current ?? ""} onChange={(e) => onChange(Number(e.target.value))} className="rounded-md border border-line bg-surface px-2 py-1 font-mono text-[12px] text-ink">
                {versions.map((version) => (
                    <option key={version.versionId} value={version.versionNo}>
                        v{version.versionNo}{version.isActive ? " (active)" : ""}
                    </option>
                ))}
            </select>
        </label>
    );
}