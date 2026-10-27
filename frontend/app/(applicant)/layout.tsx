import type { ReactNode } from "react";
import { ApplicantGnb } from "@/components/layout/applicant-gnb";
import { Footer } from "@/components/layout/footer";
import { AuthGuard } from "@/features/auth/auth-guard";
import { ResumeBanner } from "@/features/resume/resume-banner";

export default function ApplicantLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard allow={["applicant"]}>
      <div className="flex min-h-screen flex-col">
        <ApplicantGnb />
        <ResumeBanner />
        <main className="mx-auto w-full max-w-[1120px] flex-1 px-4 py-6">{children}</main>
        <Footer />
      </div>
    </AuthGuard>
  );
}
