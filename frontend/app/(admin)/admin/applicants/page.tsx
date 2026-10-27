import type { Metadata } from "next";
import { Suspense } from "react";
import { ApplicantList } from "@/features/admin/applicants/applicant-list";

export const metadata: Metadata = { title: "지원자 관리" };
export default function Page() {
  return <Suspense fallback={null}><ApplicantList /></Suspense>;
}
