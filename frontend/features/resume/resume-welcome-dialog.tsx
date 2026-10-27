"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { apiFetch } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { ME_KEY } from "@/features/auth/api";
import { useMyResume } from "@/features/applicant/api";
import { ResumeRegistration } from "./resume-registration";

const dismiss = () => apiFetch<void>("/api/v1/me/resume-popup/dismiss", { method: "POST" });

/** APP-01b 가입 직후 이력서·자소서 등록 팝업. `/jobs?welcome=1` 일 때만 마운트되며 Skip/닫기는 모두 dismiss 로 처리한다 (UI_SPEC §4.1.2). */
export function ResumeWelcomeDialog() {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  const open = sp.get("welcome") === "1";
  const mine = useMyResume();
  const close = () => { const q = new URLSearchParams(sp.toString()); q.delete("welcome"); const s = q.toString(); router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false }); };
  const skip = useMutation({
    mutationFn: dismiss,
    onSettled: (_d, err) => {  // 요청이 실패해도 팝업은 닫는다 (UX 우선, 다음 로그인 때 다시 보일 수 있음)
      void qc.invalidateQueries({ queryKey: ME_KEY });
      if (!err) toast.info("마이페이지에서 언제든 등록할 수 있어요");
      close();
    },
  });
  if (!open || mine.isLoading) return null;
  if (mine.data?.data) { return null; }  // 이미 등록한 사용자는 노출하지 않는다

  return (
    <Modal open wide title="가입을 환영합니다!" onClose={() => skip.mutate()}>
      <div className="space-y-3">
        <p className="text-sm">이력서를 미리 등록해 둘까요? 미리 등록하면 공고 지원 시 바로 불러와 사용할 수 있어요.</p>
        <p className="flex items-center gap-1 text-xs text-muted"><Lock className="h-3 w-3" aria-hidden />업로드한 파일은 기업 내부망 서버에만 저장됩니다.</p>
        <ResumeRegistration registered={null} requireComplete onSaved={() => { void qc.invalidateQueries({ queryKey: ME_KEY }); close(); }} />
        <div className="flex justify-end"><Button variant="ghost" onClick={() => skip.mutate()} loading={skip.isPending} data-testid="welcome-skip">Skip, 나중에 할게요</Button></div>
      </div>
    </Modal>
  );
}
