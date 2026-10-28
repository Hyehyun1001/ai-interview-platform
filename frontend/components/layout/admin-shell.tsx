"use client";
import { Bell, CalendarDays, ClipboardList, LayoutDashboard, Menu, ShieldAlert, Users, X, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useMetrics, useNotifications } from "@/features/admin/api";
import { cn } from "@/lib/utils";
import { UserMenu } from "./user-menu";

const NAV: { href: string; label: string; Icon: LucideIcon }[] = [
  { href: "/admin", label: "대시보드", Icon: LayoutDashboard },
  { href: "/admin/jobs", label: "공고 관리", Icon: ClipboardList },
  { href: "/admin/applicants", label: "지원자 관리", Icon: Users },
  { href: "/admin/calendar", label: "일정 관리", Icon: CalendarDays },
  { href: "/admin/history", label: "이력·알림", Icon: Bell },
];

const TITLES: [string, string][] = [
  ["/admin/applications/", "지원자 상세 평가"], ["/admin/jobs", "공고 관리"], ["/admin/applicants", "지원자 관리"],
  ["/admin/calendar", "일정 관리"], ["/admin/history", "이력·알림"], ["/admin", "대시보드"],
];
const titleOf = (path: string) => TITLES.find(([p]) => path.startsWith(p))?.[1] ?? "관리자";
const isActive = (path: string, href: string) => (href === "/admin" ? path === "/admin" : path === href || path.startsWith(`${href}/`));

const PRESSURE = {
  normal: { dot: "bg-success", label: "정상" }, warn: { dot: "bg-warning", label: "혼잡" }, critical: { dot: "bg-danger", label: "위험" },
} as const;

/** 관리자 셸 (UI_SPEC §2.4): 좌측 사이드바(lg 고정 / 모바일 Drawer) + 상단 헤더(알림 벨 · 시스템 상태 · 프로필). */
export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [drawer, setDrawer] = useState(false);
  const metrics = useMetrics();
  const notifications = useNotifications();
  const unread = notifications.data?.unread_count ?? 0;
  const ext = metrics.data?.external_transfer;

  useEffect(() => setDrawer(false), [pathname]);

  const sidebar = (
    <nav aria-label="관리자 메뉴" className="flex h-full flex-col">
      <Link href="/admin" className="flex h-16 items-center px-5 text-lg font-extrabold tracking-tight text-primary">AI Interview</Link>
      <ul className="flex-1 space-y-1 px-3 py-2">
        {NAV.map(({ href, label, Icon }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href}>
              <Link href={href} aria-current={active ? "page" : undefined}
                className={cn("flex items-center gap-3 rounded px-3 py-2.5 text-sm font-medium", active ? "bg-primary text-primary-fg" : "text-text hover:bg-surface-2")}>
                <Icon className="h-4 w-4" aria-hidden />{label}
              </Link>
            </li>
          );
        })}
      </ul>
      {ext?.enabled && (
        <div role="alert" className="m-3 rounded border border-warning/40 bg-warning-bg p-3 text-xs text-warning">
          <p className="flex items-center gap-1 font-bold"><ShieldAlert className="h-4 w-4" aria-hidden />외부 전송 활성화</p>
          <p className="mt-1">{ext.tts_edge && "TTS(edge) "}{ext.cloud_fallback && "Cloud LLM "}사용 중 · 전송 {ext.count}건</p>
        </div>
      )}
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow">본문 바로가기</a>
      <aside className="sticky top-0 hidden h-screen border-r border-border bg-surface lg:block">{sidebar}</aside>
      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="메뉴">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawer(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-surface shadow-xl">
            <button type="button" aria-label="메뉴 닫기" onClick={() => setDrawer(false)} className="absolute right-2 top-3 rounded p-2 hover:bg-surface-2"><X className="h-5 w-5" /></button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-surface px-4">
          <button type="button" aria-label="메뉴 열기" onClick={() => setDrawer(true)} className="rounded p-2 hover:bg-surface-2 lg:hidden"><Menu className="h-5 w-5" /></button>
          <h1 className="text-lg font-bold">{titleOf(pathname)}</h1>
          <div className="ml-auto flex items-center gap-2">
            {metrics.data && (
              <span title={`여유 메모리 ${metrics.data.free_gb.toFixed(1)}GB`} className="hidden items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium sm:inline-flex">
                <span className={cn("h-2 w-2 rounded-full", PRESSURE[metrics.data.pressure].dot)} aria-hidden />시스템 {PRESSURE[metrics.data.pressure].label}
              </span>
            )}
            <Link href="/admin/history" aria-label={`알림 ${unread}건`} className="relative rounded p-2 hover:bg-surface-2">
              <Bell className="h-5 w-5" aria-hidden />
              {unread > 0 && <span className="absolute right-0.5 top-0.5 min-w-4 rounded-full bg-danger px-1 text-center text-[10px] font-bold leading-4 text-white">{unread}</span>}
            </Link>
            <UserMenu />
          </div>
        </header>
        {metrics.data?.pressure === "critical" && (
          <p role="alert" className="border-b border-danger/30 bg-danger-bg px-4 py-2 text-sm text-danger">서버 메모리가 부족합니다. 진행 중 면접에 영향이 있을 수 있어요.</p>
        )}
        <main id="main" tabIndex={-1} className="mx-auto max-w-[1280px] p-4 focus-visible:outline-none lg:p-6">{children}</main>
      </div>
    </div>
  );
}
