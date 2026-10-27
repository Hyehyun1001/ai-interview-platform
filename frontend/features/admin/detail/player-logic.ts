import type { GazeEventDto, SegmentKind, TimelineSegment, TimelineWord } from "@/types/admin";

export const PRE_ROLL_MS = 1500;     // 구간 듣기: 앞뒤 맥락을 위해 1.5초 앞에서 재생
export const SEEK_STEP_MS = 5000;
export const SPEEDS = [0.75, 1, 1.25, 1.5, 2] as const;

export type SegmentFilter = "all" | "bad" | "good";

export const isHighlight = (k: SegmentKind) => k === "highlight_good" || k === "highlight_bad";

export function filterSegments(segments: TimelineSegment[], filter: SegmentFilter): TimelineSegment[] {
  if (filter === "all") return segments.filter((s) => isHighlight(s.kind) || s.kind === "stt_unclear");
  const kind: SegmentKind = filter === "bad" ? "highlight_bad" : "highlight_good";
  return segments.filter((s) => s.kind === kind);
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** 구간 재생 시작 위치 (0 미만 방지) */
export const segmentStartMs = (seg: Pick<TimelineSegment, "start_ms">) => Math.max(0, seg.start_ms - PRE_ROLL_MS);

/** 현재 시각이 속한 구간. 겹치면 하이라이트를 우선한다. */
export function segmentAt(segments: TimelineSegment[], ms: number): TimelineSegment | null {
  const hit = segments.filter((s) => ms >= s.start_ms && ms < s.end_ms);
  return hit.find((s) => isHighlight(s.kind)) ?? hit[0] ?? null;
}

/** 현재 재생 중인 단어 인덱스 (없으면 -1) — 이분 탐색 */
export function activeWordIndex(words: TimelineWord[], ms: number): number {
  const t = ms / 1000;
  let lo = 0, hi = words.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const w = words[mid]!;
    if (w.s <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  const w = ans >= 0 ? words[ans] : undefined;
  return w && t < w.e ? ans : -1;
}

/** 타임라인 막대 위치(%) */
export function toPercent(ms: number, durationMs: number): number {
  return durationMs <= 0 ? 0 : clamp((ms / durationMs) * 100, 0, 100);
}

/** 막대 위 클릭 x 좌표 → 재생 시각 */
export function pointerToMs(clientX: number, rect: { left: number; width: number }, durationMs: number): number {
  return rect.width <= 0 ? 0 : Math.round(clamp((clientX - rect.left) / rect.width, 0, 1) * durationMs);
}

/** 단축키 → 이동할 시각(없으면 null) */
export function seekByKey(key: string, currentMs: number, durationMs: number, segments: TimelineSegment[]): number | null {
  const highlights = segments.filter((s) => isHighlight(s.kind));
  switch (key) {
    case "ArrowLeft": return clamp(currentMs - SEEK_STEP_MS, 0, durationMs);
    case "ArrowRight": return clamp(currentMs + SEEK_STEP_MS, 0, durationMs);
    case "[": { const prev = [...highlights].reverse().find((s) => s.start_ms < currentMs - 1000); return prev ? segmentStartMs(prev) : null; }
    case "]": { const next = highlights.find((s) => s.start_ms > currentMs + 500); return next ? segmentStartMs(next) : null; }
    default: return null;
  }
}

export const gazeLabel: Record<GazeEventDto["kind"], string> = { gaze_away: "시선 이탈", face_lost: "얼굴 미검출", multi_face: "다중 얼굴" };

export const SEGMENT_STYLE: Record<SegmentKind, { label: string; icon: string }> = {
  highlight_good: { label: "우수", icon: "▲" }, highlight_bad: { label: "감점", icon: "▼" },
  stt_unclear: { label: "인식 불명확", icon: "?" }, silence: { label: "침묵", icon: "·" }, speech: { label: "발화", icon: "" },
};
