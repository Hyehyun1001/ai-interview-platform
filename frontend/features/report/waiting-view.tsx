"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Card, ErrorState } from "@/components/ui/primitives";
import { msToClock } from "@/lib/utils";
import { useReport } from "./api";

/** APP-08: 리포트 생성 대기. 서버 stage/progress/eta 를 보여 주고 완료되면 리포트로 이동한다. */
export function WaitingView({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const q = useReport(sessionId, true);
  const r = q.data;
  useEffect(() => { if (r?.status === "done") router.replace(`/reports/${sessionId}`); }, [r?.status, router, sessionId]);
  if (q.isError) return <Card className="mx-auto mt-16 max-w-md"><ErrorState message="리포트 상태를 확인하지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (r?.status === "failed") return <Card className="mx-auto mt-16 max-w-md space-y-3 p-8 text-center" role="alert"><h1 className="text-lg font-bold">리포트를 만들지 못했어요</h1><p className="text-sm text-muted">담당자가 확인 후 다시 생성할 수 있어요. 면접 내용은 안전하게 저장되어 있습니다.</p><Link className="text-primary" href="/jobs">공고 목록으로</Link></Card>;
  const pct = Math.round((r?.progress ?? 0.05) * 100);
  const STAGE = { transcript: "답변을 정리하고 있어요", scoring: "항목별로 평가하고 있어요", summary: "총평을 작성하고 있어요" } as const;
  return (
    <Card className="mx-auto mt-16 max-w-md space-y-4 p-8 text-center" data-testid="waiting">
      <h1 className="text-xl font-bold">면접이 끝났어요 🎉</h1>
      <p className="text-sm text-muted">{r?.stage ? STAGE[r.stage] : "리포트 생성을 기다리고 있어요"}</p>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="리포트 생성 진행률" className="h-2 overflow-hidden rounded-full bg-surface-2"><div className="h-full bg-primary transition-[width] duration-700" style={{ width: `${pct}%` }} /></div>
      <p className="text-xs text-muted">예상 남은 시간 약 {msToClock((r?.eta_sec ?? 240) * 1000)} (추정치) · 이 화면을 닫아도 마이페이지에서 확인할 수 있어요</p>
    </Card>
  );
}
