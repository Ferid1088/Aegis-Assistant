import { DocumentManageView } from "@/components/documents/document-manage-view";

export default function DocumentManagePage({ params }: { params: { docId: string } }) {
    return <DocumentManageView docId={params.docId} />;
}