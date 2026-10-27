"use client";
import { Lock, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { UserMenu } from "./user-menu";

const NAV = [{ href: "/jobs", label: "공고" }, { href: "/mypage?tab=applications", label: "내 지원현황", match: "/mypage" }];

/** 지원자 GNB (UI_SPEC §2.2): 로고 · 메뉴 · 내부망 저장 배지 · 마이페이지 아이콘(상시) · 프로필 메뉴. */
export function ApplicantGnb() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface">
      <div className="mx-auto flex h-16 max-w-[1120px] items-center gap-6 px-4">
        <Link href="/jobs" className="text-lg font-extrabold tracking-tight text-primary">AI Interview</Link>
        <nav aria-label="주 메뉴" className="flex items-center gap-1">
          {NAV.map((n) => {
            const active = pathname === (n.match ?? n.href) || pathname.startsWith(`${n.match ?? n.href}/`);
            return <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
              className={cn("rounded px-3 py-2 text-sm font-medium", active ? "bg-surface-2 text-text" : "text-muted hover:text-text")}>{n.label}</Link>;
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <span tabIndex={0} title="음성·영상·이력서는 기업 내부망 서버에만 저장됩니다"
            className="hidden items-center gap-1 rounded-full bg-info-bg px-2.5 py-1 text-xs font-semibold text-info sm:inline-flex">
            <Lock className="h-3 w-3" aria-hidden />내부망 저장
          </span>
          <Link href="/mypage" aria-label="마이페이지" className="rounded p-2 hover:bg-surface-2"><UserRound className="h-5 w-5" aria-hidden /></Link>
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
