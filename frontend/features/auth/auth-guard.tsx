"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { homeFor, useMe, type UserRole } from "./api";

/**
 * 영역별 접근 가드. 미들웨어는 HttpOnly refresh 쿠키(경로 제한)를 볼 수 없으므로, 만료된 access 토큰은 여기서
 * apiFetch 의 자동 갱신으로 복구하고 실패하면 로그인으로 보낸다. 최종 권한 판단은 항상 API(RBAC)가 한다.
 */
export function AuthGuard({ allow, children }: { allow: UserRole[]; children: ReactNode }) {
  const { data: me, error, isLoading } = useMe();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [error, pathname, router]);

  const allowed = !!me && allow.includes(me.role);
  useEffect(() => {
    if (me && !allowed) {
      toast.warning("권한이 없습니다", "FORBIDDEN_AREA");
      router.replace(homeFor(me.role));
    }
  }, [me, allowed, router]);

  if (allowed) return <>{children}</>;
  if (error && !(error instanceof ApiError && error.status === 401)) {
    return <p role="alert" className="p-8 text-center text-danger">사용자 정보를 불러오지 못했습니다. 새로고침해 주세요.</p>;
  }
  return <div className="mx-auto max-w-5xl space-y-3 p-8" aria-busy={isLoading}><Skeleton className="h-8 w-48" /><Skeleton className="h-40 w-full" /></div>;
}
