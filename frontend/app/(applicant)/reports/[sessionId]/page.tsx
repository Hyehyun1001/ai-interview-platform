import { ReportView } from "@/features/report/report-view";

export default function Page({ params }: { params: { sessionId: string } }) {
  return <ReportView sessionId={params.sessionId} />;
}
