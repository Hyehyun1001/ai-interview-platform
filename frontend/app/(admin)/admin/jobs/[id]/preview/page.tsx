import type { Metadata } from "next";
import { JobPreview } from "@/features/admin/jobs/job-preview";

export const metadata: Metadata = { title: "공고 미리보기" };
export default function Page({ params }: { params: { id: string } }) {
  return <JobPreview jobId={params.id} />;
}
