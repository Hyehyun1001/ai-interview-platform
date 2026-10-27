import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "@/features/auth/login-form";

export const metadata: Metadata = { title: "로그인" };

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-6 shadow-sm">
        <h1 className="mb-1 text-center text-xl font-bold">AI Interview</h1>
        <p className="mb-5 text-center text-sm text-muted">기업 내부망에서만 처리되는 AI 모의면접</p>
        <Suspense fallback={null}><LoginForm /></Suspense>
        <p className="mt-5 text-center text-xs text-muted">🔒 모든 음성·영상·이력서 데이터는 기업 내부망 서버 내에서만 저장·처리됩니다.</p>
      </div>
    </main>
  );
}
