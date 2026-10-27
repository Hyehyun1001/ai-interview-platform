import type { Metadata } from "next";
import { Suspense } from "react";
import { ApplicantList } from "@/features/admin/applicants/applicant-list";

export const metadata: Metadata = { title: "공고별 지원자" };
export default function Page({ params }: { params: { id: string } }) {
  return <Suspense fallback={null}><ApplicantList jobId={params.id} /></Suspense>;
}
