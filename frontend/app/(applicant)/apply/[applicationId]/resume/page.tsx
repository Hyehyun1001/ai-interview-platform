import type { Metadata } from "next";
import { ResumeStep } from "@/features/resume/resume-step";

export const metadata: Metadata = { title: "이력서 제출" };
export default function ResumeStepPage({ params }: { params: { applicationId: string } }) {
  return <ResumeStep applicationId={params.applicationId} />;
}
