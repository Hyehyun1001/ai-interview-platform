"use client";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/primitives";
import type { Extraction } from "./use-resume-extraction";

/** 업로드/추출 진행 표시 (UI_SPEC §4.3.3, §4.3.6). 스캔 문서 안내와 60초 초과 안내를 포함한다. */
export function OcrProgress({ state, onCancel, onKeepWaiting, onManual }: {
  state: Extraction; onCancel: () => void; onKeepWaiting: () => void; onManual: () => void;
}) {
  if (state.phase === "uploading") {
    return (
      <div className="space-y-1 rounded border border-border p-3" data-testid="ocr-progress">
        <div className="flex items-center justify-between text-sm"><span>{state.fileName}</span><Button variant="ghost" onClick={onCancel}>취소</Button></div>
        <div role="progressbar" aria-label="업로드 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={state.pct} className="h-2 overflow-hidden rounded-full bg-surface-2">
          <div className="h-full bg-primary transition-[width]" style={{ width: `${state.pct}%` }} />
        </div>
        <p className="text-xs text-muted">업로드 중… {state.pct}%</p>
      </div>
    );
  }
  if (state.phase === "extracting") {
    return (
      <div className="space-y-1 rounded border border-border p-3" data-testid="ocr-progress" aria-live="polite">
        <div className="flex items-center justify-between text-sm"><span className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />{state.fileName} 정보를 추출하고 있어요…</span><Button variant="ghost" onClick={onCancel}>취소</Button></div>
        <p className="text-xs text-muted">스캔 문서는 최대 30초 걸릴 수 있어요.</p>
      </div>
    );
  }
  if (state.phase === "slow") {
    return (
      <div role="alert" className="space-y-2 rounded border border-warning bg-warning-bg p-3 text-sm" data-testid="ocr-slow">
        <p>추출이 오래 걸리고 있어요.</p>
        <div className="flex gap-2"><Button variant="secondary" onClick={onKeepWaiting}>계속 기다리기</Button><Button variant="secondary" onClick={onManual}>직접 작성으로 전환</Button></div>
      </div>
    );
  }
  if (state.phase === "failed") {
    return (
      <div role="alert" className="space-y-2 rounded border border-danger bg-danger-bg p-3 text-sm text-danger" data-testid="ocr-failed">
        <p>{state.message}</p>
        <Button variant="secondary" onClick={onManual}>직접 작성으로 전환</Button>
      </div>
    );
  }
  return null;
}
