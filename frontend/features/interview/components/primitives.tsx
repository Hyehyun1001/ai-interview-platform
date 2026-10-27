"use client";
import { Mic, ShieldAlert, Video } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn, msToClock } from "@/lib/utils";
import { GAZE_BANNER_MS, type InterviewState } from "../store";

// ── 진행률 (UI_SPEC §4.6.4 ③) ────────────────────────────────────────────────
export function InterviewProgressBar({ main, total, followupLabel, codingEnabled }: { main: number; total: number; followupLabel?: string; codingEnabled: boolean }) {
  const pct = total > 0 ? Math.min(100, Math.round((Math.max(0, main - 1) / total) * 100)) : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-semibold">질문 {main} / {total}{followupLabel && <span className="ml-2 font-normal text-muted">({followupLabel})</span>}</span>
        {codingEnabled && <span className="text-xs text-muted">마지막: 코딩테스트</span>}
      </div>
      <div role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={main} aria-label="면접 진행률" className="h-2 overflow-hidden rounded-full bg-surface-2">
        <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── AI 면접관 + 자막 (VOI-1) ─────────────────────────────────────────────────
export function InterviewerPanel({ text, kind, speaking, captionOnly }: { text: string | null; kind?: string; speaking: boolean; captionOnly: boolean }) {
  return (
    <div className="flex h-full flex-col items-center gap-5 rounded-lg border border-border bg-surface p-6">
      <div aria-hidden className={cn("flex h-24 w-24 items-center justify-center rounded-full bg-primary text-3xl text-primary-fg transition", speaking && "animate-pulse ring-8 ring-primary/20")}>◉</div>
      <div className="w-full flex-1">
        {kind && kind !== "main" && <span className="mb-2 inline-block rounded-full bg-info-bg px-2 py-0.5 text-xs font-semibold text-info">{kind === "followup" ? "꼬리질문" : "코드 질문"}</span>}
        {/* 자막은 TTS 와 무관하게 질문 도착 즉시 보인다 — TTS 가 실패해도 질문이 전달된다 (청각 접근성) */}
        <p data-testid="caption" role="status" aria-live="polite" className="min-h-[5rem] rounded bg-surface-2 p-4 text-lg font-medium leading-relaxed">
          {text ?? <span className="text-muted">질문을 준비하고 있어요…</span>}
        </p>
        {captionOnly && <p className="mt-2 text-xs text-muted">음성 재생을 사용할 수 없어 자막으로 진행합니다.</p>}
      </div>
    </div>
  );
}

// ── 웹캠 오버레이 (VOI-4) ────────────────────────────────────────────────────
const GAZE_DOT: Record<InterviewState["gazeStatus"], { cls: string; label: string }> = {
  unknown: { cls: "bg-muted", label: "시선 분석 준비 중" }, ok: { cls: "bg-success", label: "시선 정상" },
  away: { cls: "bg-warning", label: "시선 이탈 감지 중" }, lost: { cls: "bg-muted", label: "얼굴 미검출" },
};

export function WebcamOverlay({ stream, onVideo, gazeStatus, recording }: { stream: MediaStream | null; onVideo: (el: HTMLVideoElement | null) => void; gazeStatus: InterviewState["gazeStatus"]; recording: boolean }) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => { if (ref.current) ref.current.srcObject = stream; }, [stream]);
  const dot = GAZE_DOT[gazeStatus];
  return (
    <div className="relative overflow-hidden rounded-lg bg-black">
      {/* 화면 표시만 좌우 반전(거울). 녹화 원본은 반전하지 않는다 (UI_SPEC §4.6.4 ④) */}
      <video ref={(el) => { ref.current = el; onVideo(el); }} autoPlay muted playsInline aria-label="내 웹캠 화면" data-testid="webcam" className="aspect-[4/3] w-full -scale-x-100 object-cover" />
      {recording && <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded bg-black/60 px-1.5 py-0.5 text-xs font-bold text-white"><span className="h-2 w-2 animate-pulse rounded-full bg-danger" aria-hidden />REC</span>}
      <span className="absolute bottom-2 left-2 inline-flex items-center gap-1.5 rounded bg-black/60 px-2 py-0.5 text-xs text-white" data-testid="gaze-status" data-status={gazeStatus}>
        <span className={cn("h-2 w-2 rounded-full", dot.cls)} aria-hidden />{dot.label}
      </span>
      {!stream && <p className="absolute inset-0 flex items-center justify-center text-sm text-white/70"><Video className="mr-2 h-4 w-4" aria-hidden />카메라 연결 중…</p>}
    </div>
  );
}

// ── 답변 타이머 (VOI-3) ──────────────────────────────────────────────────────
export function useRemainingMs(deadline: number | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (deadline === null) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [deadline]);
  return deadline === null ? null : Math.max(0, deadline - now);
}

export const WARN_SECONDS = 10;

export function AnswerTimer({ remainingMs, totalSec }: { remainingMs: number | null; totalSec: number }) {
  const active = remainingMs !== null;
  const sec = active ? Math.ceil(remainingMs / 1000) : totalSec;
  const frac = active && totalSec > 0 ? Math.min(1, remainingMs / (totalSec * 1000)) : 1;
  const warn = active && sec <= WARN_SECONDS;
  const r = 52, c = 2 * Math.PI * r;
  const announced = useRef(false);
  const [announce, setAnnounce] = useState("");
  useEffect(() => {
    if (warn && !announced.current) { announced.current = true; setAnnounce(`${WARN_SECONDS}초 남았습니다`); }  // 스크린리더에는 1회만 알린다
    if (!warn) announced.current = false;
  }, [warn]);
  return (
    <div className="flex flex-col items-center gap-1" data-testid="answer-timer" data-warn={warn}>
      <p className="text-xs font-medium text-muted">답변 남은 시간</p>
      <div className="relative h-32 w-32">
        <svg viewBox="0 0 120 120" className="-rotate-90" aria-hidden>
          <circle cx="60" cy="60" r={r} fill="none" strokeWidth="8" className="stroke-surface-2" />
          <circle cx="60" cy="60" r={r} fill="none" strokeWidth="8" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - frac)}
            className={cn("transition-[stroke-dashoffset] duration-300", warn ? "stroke-danger" : "stroke-primary")} />
        </svg>
        <span className={cn("absolute inset-0 flex items-center justify-center text-2xl font-bold tabular-nums", warn && "animate-pulse text-danger", !active && "text-muted")} data-testid="timer-value">
          {msToClock(sec * 1000)}
        </span>
      </div>
      <span className="sr-only" aria-live="polite">{announce}</span>
    </div>
  );
}

// ── 마이크 레벨 (PRE/INT) ────────────────────────────────────────────────────
export function MicLevelMeter({ level, listening }: { level: number; listening: boolean }) {
  const bars = 10;
  const lit = Math.round(level * bars);
  return (
    <div className="flex items-center gap-2" aria-label={listening ? "마이크 입력 레벨" : "마이크 대기 중"} role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={Number(level.toFixed(2))}>
      <Mic className={cn("h-4 w-4", listening ? "text-primary" : "text-muted")} aria-hidden />
      <div className="flex flex-1 gap-0.5" aria-hidden>
        {Array.from({ length: bars }, (_, i) => <span key={i} className={cn("h-3 flex-1 rounded-sm", listening && i < lit ? "bg-success" : "bg-surface-2")} />)}
      </div>
    </div>
  );
}

// ── 배너 ─────────────────────────────────────────────────────────────────────
/** 시선 경고: 부정행위를 단정하지 않는 문구는 서버가 만든다 (TRD §4.4). 레이아웃을 밀지 않도록 오버레이로 띄운다. */
export function GazeWarningBanner({ gaze }: { gaze: InterviewState["gaze"] }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!gaze) return;
    setVisible(true);
    const t = setTimeout(() => setVisible(false), Math.min(GAZE_BANNER_MS, Math.max(0, gaze.visibleUntil - Date.now())));
    return () => clearTimeout(t);
  }, [gaze]);
  if (!gaze || !visible) return null;
  return (
    <div role="alert" data-testid="gaze-banner" className="pointer-events-auto fixed left-1/2 top-16 z-40 flex w-[min(92vw,560px)] -translate-x-1/2 items-center gap-2 rounded border border-warning/40 bg-warning-bg px-4 py-2.5 text-sm font-medium text-warning shadow-md">
      <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden />
      <span className="flex-1">{gaze.message} ({gaze.count}/3)</span>
      <button type="button" onClick={() => setVisible(false)} className="rounded px-1.5 py-0.5 text-xs hover:bg-black/10" aria-label="경고 닫기">닫기</button>
    </div>
  );
}

export function NoticeBanner({ tone, children }: { tone: "warning" | "info"; children: React.ReactNode }) {
  return <p role="status" className={cn("rounded px-4 py-2.5 text-sm font-medium", tone === "warning" ? "bg-warning-bg text-warning" : "bg-info-bg text-info")}>{children}</p>;
}
