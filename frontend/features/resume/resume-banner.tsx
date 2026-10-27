"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMyResume } from "@/features/applicant/api";
import { useMe } from "@/features/auth/api";

/** 가입 팝업을 Skip 한 뒤에도 이력서가 없거나 기본 정보가 비어 있으면 GNB 아래 배너로 안내한다 (PRD 10장 #12). 마이페이지에서는 숨긴다. */
export function ResumeBanner() {
  const me = useMe();
  const resume = useMyResume();
  const pathname = usePathname();
  if (!me.data?.resume_popup_dismissed_at || resume.isLoading || pathname.startsWith("/mypage")) return null;
  if (resume.data?.basic_info_complete) return null;
  return (
    <div role="status" className="border-b border-warning/30 bg-warning-bg" data-testid="resume-banner">
      <div className="mx-auto flex max-w-[1120px] items-center gap-3 px-4 py-2 text-sm">
        <span>이력서를 등록해 두면 공고 지원이 빨라져요.</span>
        <Link href="/mypage?tab=resume" className="font-semibold text-primary hover:underline">지금 등록하기 ›</Link>
      </div>
    </div>
  );
}
