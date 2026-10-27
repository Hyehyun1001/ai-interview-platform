import type { ReactNode } from "react";
import { AuthGuard } from "@/features/auth/auth-guard";

/** 면접 중에는 GNB·푸터를 숨겨 몰입을 유지하고 실수로 이탈하지 않게 한다 (UI_SPEC §4.6). */
export default function InterviewLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard allow={["applicant"]}>
      <main className="min-h-screen bg-bg">{children}</main>
    </AuthGuard>
  );
}
