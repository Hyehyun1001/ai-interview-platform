"use client";
import { Pause, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, EmptyState } from "@/components/ui/primitives";
import { cn, msToClock } from "@/lib/utils";
import type { TimelineSegment, TimelineTurn } from "@/types/admin";
import { SEGMENT_STYLE, SPEEDS, activeWordIndex, clamp, filterSegments, gazeLabel, isHighlight, pointerToMs, segmentAt, segmentStartMs, seekByKey, toPercent, type SegmentFilter } from "./player-logic";

/** 문항 1개의 음성 타임라인 + 하이라이트 구간 재생 (ADM-06). 우수=▲(초록), 감점=▼(빨강) — 색 외에 아이콘/라벨로도 구분한다. */
export function HighlightPlayer({ turn }: { turn: TimelineTurn }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const stopAtRef = useRef<number | null>(null);
  const [posMs, setPosMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [filter, setFilter] = useState<SegmentFilter>("all");
  const [stopAtEnd, setStopAtEnd] = useState(true);
  const [speed, setSpeed] = useState<number>(1);
  const [audioError, setAudioError] = useState(false);
  const duration = turn.duration_ms;

  useEffect(() => { setPosMs(0); setPlaying(false); setAudioError(false); stopAtRef.current = null; }, [turn.turn_id]);

  const seek = useCallback((ms: number) => {
    const a = audioRef.current;
    const v = clamp(ms, 0, duration);
    if (a) a.currentTime = v / 1000;
    setPosMs(v);
  }, [duration]);

  const toggle = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) { stopAtRef.current = null; void a.play().catch(() => setAudioError(true)); } else a.pause();
  }, []);

  const playSegment = (seg: TimelineSegment) => {
    const a = audioRef.current;
    if (!a) return;
    seek(segmentStartMs(seg));
    stopAtRef.current = stopAtEnd ? seg.end_ms : null;
    void a.play().catch(() => setAudioError(true));
  };

  const onTime = () => {
    const a = audioRef.current;
    if (!a) return;
    const ms = a.currentTime * 1000;
    setPosMs(ms);
    if (stopAtRef.current !== null && ms >= stopAtRef.current) { a.pause(); stopAtRef.current = null; }
  };

  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = speed; }, [speed]);

  const onKey = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).tagName === "SELECT" || (e.target as HTMLElement).tagName === "INPUT") return;
    if (e.key === " ") { e.preventDefault(); toggle(); return; }
    if (e.key === "+" || e.key === "-") { const i = SPEEDS.indexOf(speed as (typeof SPEEDS)[number]); const n = SPEEDS[clamp(i + (e.key === "+" ? 1 : -1), 0, SPEEDS.length - 1)]; if (n) setSpeed(n); return; }
    const to = seekByKey(e.key, posMs, duration, turn.segments);
    if (to !== null) { e.preventDefault(); seek(to); }
  };

  const visible = useMemo(() => filterSegments(turn.segments, filter), [turn.segments, filter]);
  const current = segmentAt(turn.segments, posMs);
  const words = useMemo(() => turn.segments.flatMap((s) => s.words ?? []), [turn.segments]);
  const wi = activeWordIndex(words, posMs);
  const barRef = useRef<HTMLDivElement>(null);

  if (!turn.audio_url) {
    return <EmptyState title="음성이 보관 기간 경과로 삭제되었습니다" description="텍스트 답변과 평가 결과는 그대로 확인할 수 있어요." />;
  }

  return (
    <div className="space-y-3" onKeyDown={onKey} data-testid="highlight-player">
      <audio ref={audioRef} src={turn.audio_url} preload="metadata" onTimeUpdate={onTime} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onError={() => setAudioError(true)} />
      {audioError && <p role="alert" className="rounded bg-danger-bg p-2 text-sm text-danger">음성을 재생할 수 없어요. 잠시 후 다시 시도해 주세요.</p>}

      <div className="flex items-center gap-3">
        <button type="button" onClick={toggle} aria-label={playing ? "일시정지" : "재생"} className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-primary-fg" data-testid="play-toggle">
          {playing ? <Pause className="h-5 w-5" aria-hidden /> : <Play className="h-5 w-5" aria-hidden />}
        </button>
        <span className="text-sm tabular-nums" data-testid="player-time">{msToClock(posMs)} / {msToClock(duration)}</span>
        <label className="ml-auto flex items-center gap-1 text-xs">속도
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="h-8 rounded border border-border bg-surface px-1">{SPEEDS.map((s) => <option key={s} value={s}>{s}x</option>)}</select></label>
        <label className="flex items-center gap-1 text-xs">볼륨<input type="range" min={0} max={1} step={0.05} defaultValue={1} onChange={(e) => { if (audioRef.current) audioRef.current.volume = Number(e.target.value); }} aria-label="볼륨" /></label>
      </div>

      {/* 타임라인 트랙 */}
      <div ref={barRef} role="slider" tabIndex={0} aria-label="재생 위치" aria-valuemin={0} aria-valuemax={Math.round(duration / 1000)} aria-valuenow={Math.round(posMs / 1000)} aria-valuetext={`${msToClock(posMs)} / ${msToClock(duration)}`}
        onClick={(e) => { if (barRef.current) seek(pointerToMs(e.clientX, barRef.current.getBoundingClientRect(), duration)); }}
        className="relative h-10 cursor-pointer rounded bg-surface-2" data-testid="timeline-track">
        {turn.segments.filter((s) => s.kind === "silence" || s.kind === "stt_unclear").map((s, i) => (
          <span key={`m${i}`} className={cn("absolute inset-y-0 opacity-40", s.kind === "silence" ? "bg-muted" : "bg-warning")} style={{ left: `${toPercent(s.start_ms, duration)}%`, width: `${Math.max(0.5, toPercent(s.end_ms - s.start_ms, duration))}%` }} aria-hidden />
        ))}
        {turn.segments.filter((s) => isHighlight(s.kind)).map((s, i) => (
          <span key={`h${i}`} data-kind={s.kind} title={`${SEGMENT_STYLE[s.kind].label} ${msToClock(s.start_ms)}`}
            className={cn("absolute bottom-0 h-3/5 rounded-t text-center text-[10px] leading-6 text-white", s.kind === "highlight_good" ? "bg-success" : "bg-danger", s.kind === "highlight_bad" && "bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(255,255,255,.35)_4px,rgba(255,255,255,.35)_8px)] bg-danger")}
            style={{ left: `${toPercent(s.start_ms, duration)}%`, width: `${Math.max(1.5, toPercent(s.end_ms - s.start_ms, duration))}%` }}>{SEGMENT_STYLE[s.kind].icon}</span>
        ))}
        {turn.gaze_events.map((g, i) => (
          <span key={`g${i}`} title={`${gazeLabel[g.kind]} ${msToClock(g.start_ms)}`} className="absolute top-0 h-1.5 rounded bg-warning" style={{ left: `${toPercent(g.start_ms, duration)}%`, width: `${Math.max(0.8, toPercent(g.end_ms - g.start_ms, duration))}%` }} />
        ))}
        <span className="absolute inset-y-0 w-0.5 bg-text" style={{ left: `${toPercent(posMs, duration)}%` }} aria-hidden data-testid="playhead" />
      </div>
      <p className="text-xs text-muted">▲ 우수 · ▼ 감점(빗금) · 상단 주황선 = 시선 이탈/얼굴 미검출 · 단축키: Space 재생, ←/→ 5초, [ ] 이전/다음 구간, +/- 속도</p>

      {/* 현재 구간 / 단어 동기 */}
      {current && isHighlight(current.kind) && current.ai_comment && <p className="rounded bg-surface-2 p-2 text-sm" aria-live="polite"><b>{SEGMENT_STYLE[current.kind].label}</b> · {current.ai_comment}</p>}
      {words.length > 0 && (
        <p className="rounded border border-border p-3 text-sm leading-relaxed" data-testid="transcript">
          {words.map((w, i) => <span key={i} className={cn(i === wi && "rounded bg-primary/20 font-semibold", (w.p ?? 1) < 0.5 && "underline decoration-dotted")}>{w.w} </span>)}
        </p>
      )}
      {words.length === 0 && turn.answer_text && <p className="rounded border border-border p-3 text-sm leading-relaxed">{turn.answer_text}</p>}

      {/* 구간 목록 */}
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="구간 필터" className="flex gap-1">
          {(["all", "bad", "good"] as const).map((f) => <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)} className="rounded border border-border px-2 py-1 text-xs aria-pressed:bg-primary aria-pressed:text-primary-fg">{f === "all" ? "전체" : f === "bad" ? "▼ 감점" : "▲ 우수"}</button>)}
        </div>
        <label className="ml-auto flex items-center gap-1 text-xs"><input type="checkbox" checked={stopAtEnd} onChange={(e) => setStopAtEnd(e.target.checked)} />구간 끝에서 정지</label>
      </div>
      {visible.length === 0 ? <p className="text-sm text-muted">해당하는 구간이 없어요.</p> : (
        <ul className="space-y-2" data-testid="segment-list">
          {visible.map((s, i) => (
            <li key={i} className="flex items-start gap-3 rounded border border-border p-3">
              <Badge tone={s.kind === "highlight_good" ? "success" : s.kind === "highlight_bad" ? "danger" : "warning"}>{SEGMENT_STYLE[s.kind].icon} {SEGMENT_STYLE[s.kind].label}</Badge>
              <div className="flex-1 text-sm"><p className="tabular-nums text-xs text-muted">{msToClock(s.start_ms)} – {msToClock(s.end_ms)}</p>
                {s.text && <p>“{s.text}”</p>}{s.ai_comment && <p className="text-muted">{s.ai_comment}</p>}</div>
              <button type="button" onClick={() => playSegment(s)} className="whitespace-nowrap rounded border border-border px-2 py-1 text-xs hover:bg-surface-2">▶ 이 구간 듣기</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
