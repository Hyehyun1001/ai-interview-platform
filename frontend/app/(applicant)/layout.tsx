import { Suspense, type ReactNode } from "react";
import { ApplicantGnb } from "@/components/layout/applicant-gnb";
import { Footer } from "@/components/layout/footer";
import { ApplicantAreaGuard } from "@/features/auth/auth-guard";
import { ResumeBanner } from "@/features/resume/resume-banner";

export default function ApplicantLayout({ children }: { children: ReactNode }) {
  return (
    <ApplicantAreaGuard>
      <div className="flex min-h-screen flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow">본문 바로가기</a>
        <ApplicantGnb />
        <Suspense fallback={null}><ResumeBanner /></Suspense>
        <main id="main" tabIndex={-1} className="mx-auto focus-visible:outline-none w-full max-w-[1120px] flex-1 px-4 py-6">{children}</main>
        <Footer />
      </div>
    </ApplicantAreaGuard>
  );
}
