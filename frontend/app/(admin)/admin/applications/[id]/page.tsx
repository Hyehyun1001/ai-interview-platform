import { ApplicationDetailView } from "@/features/admin/detail/application-detail-view";

export default function ApplicationDetailPage({ params }: { params: { id: string } }) {
  return <ApplicationDetailView applicationId={params.id} />;
}
