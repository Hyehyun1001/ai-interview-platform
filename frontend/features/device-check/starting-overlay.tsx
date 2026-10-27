"use client";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/primitives";
import { START_STAGE_TEXT } from "./device-logic";

export type StartPhase =
  | { kind: "starting"; stage: string }
  | { kind: "queued"; retryInSec: number }
  | { kind: "timeout" }
  | { kind: "degraded" };

/** 면접 시작 대기 전체 화면 (UI_SPEC §4.5.4, §4.5.6): 준비 단계 안내 / 동시 면접 한도 대기 / 지연 / 경량 모드 고지. */
export function StartingOverlay({ phase, onRetry, onCancel, onProceed }: { phase: StartPhase; onRetry: () => void; onCancel: () => void; onProceed: () => void }) {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    if (phase.kind !== "starting") { setSec(0); return; }
    const t = setInterval(() => setSec((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [phase.kind]);

  return (
    <div role="alertdialog" aria-modal="true" aria-label="면접 준비" data-testid="starting-overlay" className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md space-y-4 rounded-lg bg-surface p-8 text-center shadow-xl">
        {phase.kind === "starting" && (
          <>
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary" aria-hidden />
            <h2 className="text-lg font-bold">AI 면접관을 준비하고 있어요…</h2>
            <p role="status" className="text-sm text-muted" data-testid="start-stage">{START_STAGE_TEXT[phase.stage] ?? "잠시만 기다려 주세요"} · {sec}초</p>
          </>
        )}
        {phase.kind === "queued" && (
          <>
            <h2 className="text-lg font-bold">현재 다른 지원자가 면접 중입니다</h2>
            <p role="status" className="text-sm text-muted" data-testid="start-queued">잠시 후 다시 시도해 주세요. {phase.retryInSec}초 뒤 자동으로 다시 확인합니다.</p>
            <div className="flex justify-center gap-2"><Button onClick={onRetry}>지금 다시 시도</Button><Button variant="secondary" onClick={onCancel}>취소</Button></div>
          </>
        )}
        {phase.kind === "timeout" && (
          <>
            <h2 className="text-lg font-bold">준비가 지연되고 있어요</h2>
            <p className="text-sm text-muted">잠시 후 다시 시도해 주세요. 계속 반복되면 담당자에게 문의해 주세요.</p>
            <div className="flex justify-center gap-2"><Button onClick={onRetry}>다시 시도</Button><Button variant="secondary" onClick={onCancel}>취소</Button></div>
          </>
        )}
        {phase.kind === "degraded" && (
          <>
            <h2 className="text-lg font-bold">시스템이 혼잡해요</h2>
            <p className="text-sm text-muted" data-testid="start-degraded">경량 모드로 진행될 수 있어요. 그대로 진행하거나 나중에 다시 시도할 수 있습니다.</p>
            <div className="flex justify-center gap-2"><Button onClick={onProceed}>그대로 진행</Button><Button variant="secondary" onClick={onCancel}>나중에 하기</Button></div>
          </>
        )}
      </div>
    </div>
  );
}
