"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { SignupModal } from "./signup-modal";

/** 로그인 카드 하단 [회원가입] — `?signup=1` 로 모달을 열고 닫는다 (UI_SPEC §4.1.1, 메인 이동 없음). */
export function SignupLink() {
  const router = useRouter();
  const sp = useSearchParams();
  const open = sp.get("signup") === "1";
  const set = (on: boolean) => { const q = new URLSearchParams(sp.toString()); if (on) q.set("signup", "1"); else q.delete("signup"); const s = q.toString(); router.replace(s ? `/login?${s}` : "/login", { scroll: false }); };
  return (
    <>
      <p className="mt-4 text-center text-sm text-muted">계정이 없으신가요? <button type="button" onClick={() => set(true)} className="font-semibold text-primary hover:underline">회원가입</button></p>
      <SignupModal open={open} onClose={() => set(false)} />
    </>
  );
}
