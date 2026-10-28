import type { Metadata } from "next";
import { Suspense } from "react";
import { JobList } from "@/features/admin/jobs/job-list";

export const metadata: Metadata = { title: "공고 관리" };
export default function Page() {
  return <Suspense fallback={null}><JobList /></Suspense>;
}
