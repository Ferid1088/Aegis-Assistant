import { ViewerLayout } from "@/components/viewer/viewer-layout";

function parseRegion(raw: string | undefined): [number, number, number, number] | null {
    if (!raw) return null;
    const values = raw.split(",").map((value) => Number(value));
    if (values.length !== 4 || values.some((value) => Number.isNaN(value))) return null;
    return [values[0], values[1], values[2], values[3]];
}

export default function ViewerPage({
    params,
    searchParams,
}: {
    params: { docId: string };
    searchParams: { v?: string; page?: string; region?: string };
}) {
    return (
        <ViewerLayout
            docId={params.docId}
            initialVersion={searchParams.v ? Number(searchParams.v) : undefined}
            initialPage={searchParams.page ? Number(searchParams.page) : 1}
            initialRegion={parseRegion(searchParams.region)}
        />
    );
}