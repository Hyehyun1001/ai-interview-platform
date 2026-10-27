import type { Metadata } from "next";
import { Suspense } from "react";
import { JobList } from "@/features/jobs/job-list";
import { ResumeWelcomeDialog } from "@/features/resume/resume-welcome-dialog";

export const metadata: Metadata = { title: "공고" };
export default function JobsPage() {
  return <Suspense fallback={null}><JobList /><ResumeWelcomeDialog /></Suspense>;
}
