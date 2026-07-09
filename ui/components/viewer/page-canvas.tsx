"use client";

export function PageCanvas({
    docId,
    versionNo,
    page,
    highlights = [],
}: {
    docId: string;
    versionNo?: number;
    page: number;
    highlights?: [number, number, number, number][];
}) {
    const src = `/api/v1/documents/${docId}/render?v=${versionNo ?? ""}&page=${page}`;
    return (
        <div className="mx-auto max-w-4xl">
            <div className="relative overflow-hidden rounded-card border border-line bg-surface shadow-card">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={src} alt={`Page ${page}`} className="block w-full" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                <div className="pointer-events-none absolute inset-0">
                    {highlights.map((region, index) => (
                        <div
                            key={index}
                            className="absolute rounded-sm bg-accent/25 ring-1 ring-accent/50"
                            style={{
                                left: `${region[0] * 100}%`,
                                top: `${region[1] * 100}%`,
                                width: `${(region[2] - region[0]) * 100}%`,
                                height: `${(region[3] - region[1]) * 100}%`,
                            }}
                        />
                    ))}
                </div>
            </div>
        </div>
    );
}