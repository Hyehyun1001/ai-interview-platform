import type { Metadata } from "next";
import { JobDetailView } from "@/features/jobs/job-detail";

export const metadata: Metadata = { title: "공고 상세" };
export default function JobDetailPage({ params }: { params: { jobId: string } }) {
  return <JobDetailView jobId={params.jobId} />;
}
