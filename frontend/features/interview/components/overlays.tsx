"use client";
import { Loader2, Mic, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Card } from "@/components/ui/primitives";
import type { MediaError } from "../use-media-capture";
import type { InterviewState } from "../store";

/** 시작 게이트: 오디오 자동재생·카메라/마이크 권한은 사용자 제스처가 있어야 하므로 버튼 클릭으로 시작한다. */
export function StartGate({ onStart, busy, error }: { onStart: () => void; busy: boolean; error: MediaError | null }) {
  return (
    <Card className="mx-auto mt-16 max-w-md space-y-4 p-8 text-center">
      <Mic className="mx-auto h-10 w-10 text-primary" aria-hidden />
      <h1 className="text-xl font-bold">AI 모의면접을 시작합니다</h1>
      <p className="text-sm text-muted">카메라와 마이크 사용을 허용해 주세요. 영상은 이 기기에서 시선 분석에만 쓰이며, 면접 녹화는 사내 서버에만 저장됩니다.</p>
      {error && <p role="alert" data-testid="media-error" className="rounded bg-danger-bg p-3 text-left text-sm text-danger">{error.message}</p>}
      <Button onClick={onStart} loading={busy} className="w-full" data-testid="start-btn">면접 시작</Button>
    </Card>
  );
}

export function CountdownOverlay({ n }: { n: number | null }) {
  if (n === null) return null;
  return (
    <div role="status" aria-live="assertive" data-testid="countdown" className="fixed inset-0 z-30 flex flex-col items-center justify-center bg-black/60 text-white">
      <p className="mb-2 text-lg">잠시 후 답변을 시작해 주세요</p>
      <span className="text-8xl font-black tabular-nums">{n}</span>
    </div>
  );
}

const STAGE_LABEL: Record<string, string> = { stt: "답변을 텍스트로 옮기고 있어요", analysis: "답변을 분석하고 있어요", generation: "다음 질문을 준비하고 있어요" };

export function ThinkingIndicator({ stage, since }: { stage: string | null; since: number }) {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    setSec(0);
    const id = setInterval(() => setSec(Math.floor((Date.now() - since) / 1000)), 1000);
    return () => clearInterval(id);
  }, [since]);
  return (
    <div role="status" aria-live="polite" data-testid="thinking" className="flex flex-col items-center gap-2 py-4 text-center">
      <Loader2 className="h-6 w-6 animate-spin text-primary" aria-hidden />
      <p className="text-sm font-medium">{STAGE_LABEL[stage ?? ""] ?? "잠시만 기다려 주세요"}</p>
      {sec > 10 && sec <= 45 && <p className="text-xs text-muted">조금 더 걸리고 있어요. 곧 이어집니다.</p>}
      {sec > 45 && <p className="text-xs text-warning">평소보다 오래 걸립니다. 연결은 유지되고 있으니 잠시만 더 기다려 주세요.</p>}
    </div>
  );
}

export function ReconnectOverlay({ attempt, max }: { attempt: number; max: number }) {
  return (
    <div role="alert" data-testid="reconnecting" className="fixed inset-0 z-40 flex flex-col items-center justify-center gap-3 bg-black/70 text-white">
      <WifiOff className="h-8 w-8" aria-hidden />
      <p className="text-lg font-semibold">연결이 끊겼어요. 다시 연결하는 중… ({attempt}/{max})</p>
      <p className="text-sm text-white/80">답변은 안전하게 저장되어 있습니다.</p>
    </div>
  );
}

export function FailureScreen({ state, onRetry, onExit }: { state: Pick<InterviewState, "phase" | "failure">; onRetry: () => void; onExit: () => void }) {
  const f = state.failure;
  const blocked = state.phase === "blocked";
  const retryable = f?.kind === "network" || f?.kind === "slot" || f?.kind === "conflict";
  return (
    <Card className="mx-auto mt-16 max-w-md space-y-4 p-8 text-center" role="alert" data-testid="failure">
      <h1 className="text-lg font-bold">{blocked ? "지금은 면접을 진행할 수 없어요" : "문제가 발생했어요"}</h1>
      <p className="text-sm text-muted">{f?.message ?? "알 수 없는 오류가 발생했습니다."}</p>
      <div className="flex justify-center gap-2">
        {retryable && <Button onClick={onRetry}>다시 연결</Button>}
        <Button variant="secondary" onClick={onExit}>나가기</Button>
      </div>
    </Card>
  );
}

export function AnswerDoneButton({ enabled, onClick }: { enabled: boolean; onClick: () => void }) {
  return (
    <Button onClick={onClick} disabled={!enabled} className="h-12 w-full text-base" data-testid="answer-done">
      답변 완료
    </Button>
  );
}
