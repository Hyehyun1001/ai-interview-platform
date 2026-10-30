"use client";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/primitives";
import { Drawer } from "@/components/ui/drawer";
import { logout, useMe } from "@/features/auth/api";
import { toast } from "@/lib/toast";
import { MyPagePanel, parseMyPageTab, type MyPageTab } from "./mypage-view";

/** 지원자 GNB 의 계정 버튼 + 오른쪽 마이페이지 패널. 열림 상태와 탭은 URL `?mypage=` 로 유지해 뒤로가기·새로고침·딥링크가 동작한다. */
export function MyPageDrawer() {
  const sp = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me, isLoading } = useMe();
  const tab = parseMyPageTab(sp.get("mypage"));

  const go = (next: MyPageTab | null) => {
    const q = new URLSearchParams(sp.toString());
    if (next) q.set("mypage", next); else q.delete("mypage");
    const s = q.toString();
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  };
  const onLogout = async () => {
    try { await logout(); } catch { /* 이미 만료된 세션이어도 로컬 상태는 정리한다 */ }
    qc.clear();
    toast.info("로그아웃되었습니다");
    router.replace("/login");
  };

  if (!me && !isLoading) {  // 비로그인: 공고는 열람 가능, 로그인 버튼만 노출
    return <Link href={`/login?next=${encodeURIComponent(pathname)}`} data-testid="gnb-login" className="inline-flex h-10 items-center rounded-full bg-primary px-4 text-sm font-semibold text-primary-fg hover:opacity-90">로그인</Link>;
  }
  return (
    <>
      <button type="button" onClick={() => go(tab ? null : "applications")} aria-haspopup="dialog" aria-expanded={tab !== null} aria-label="마이페이지 열기" data-testid="account-btn"
        className="flex h-10 items-center gap-2 rounded-full px-2 hover:bg-surface-2 sm:pr-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary"><UserRound className="h-5 w-5" aria-hidden /></span>
        <span className="hidden max-w-[7rem] truncate text-sm font-medium sm:inline">{me?.name ?? ""}</span>
      </button>
      <Drawer open={tab !== null} onClose={() => go(null)}
        title={<div><h2 className="text-lg font-bold">마이페이지</h2><p className="truncate text-xs text-muted" data-testid="drawer-user">{me ? `${me.name} · ${me.email}` : ""}</p></div>}
        footer={<Button variant="ghost" onClick={() => void onLogout()} className="w-full justify-start text-muted" data-testid="logout-btn"><LogOut className="h-4 w-4" aria-hidden />로그아웃</Button>}>
        {tab && <MyPagePanel tab={tab} onTab={(t) => go(t)} />}
      </Drawer>
    </>
  );
}
