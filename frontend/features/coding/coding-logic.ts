import type { Language } from "./api";

export const VERDICT_LABEL: Record<string, string> = {
  AC: "정답", WA: "오답", TLE: "시간 초과", MLE: "메모리 초과", RE: "런타임 오류", CE: "컴파일 오류", OLE: "출력 초과",
};
export const verdictTone = (v: string): "success" | "danger" | "warning" => (v === "AC" ? "success" : v === "WA" ? "danger" : "warning");

export const MONACO_LANG: Record<Language, string> = { python: "python", java: "java", javascript: "javascript" };
export const MAX_FOLLOWUP_CHARS = 2000;

const draftKey = (sid: string, lang: string) => `ai-interview:code:${sid}:${lang}`;
const startKey = (sid: string) => `ai-interview:coding-start:${sid}`;

/** 에디터 자동 저장 (UI_SPEC §4.7): 서버 저장은 제출 시뿐이고, 새로고침에는 sessionStorage 로 복원한다. 저장소를 못 쓰는 환경에서는 조용히 무시한다. */
export function loadDraft(sid: string, lang: string): string | null {
  try { return sessionStorage.getItem(draftKey(sid, lang)); } catch { return null; }
}
export function saveDraft(sid: string, lang: string, source: string): void {
  try { sessionStorage.setItem(draftKey(sid, lang), source); } catch { /* 저장 불가 */ }
}

/** 코딩테스트 시작 시각(epoch ms). 처음 문제를 받은 시점을 기록해 새로고침해도 타이머가 이어진다. */
export function codingStartedAt(sid: string, now = Date.now()): number {
  try {
    const raw = sessionStorage.getItem(startKey(sid));
    const n = raw ? Number(raw) : NaN;
    if (Number.isFinite(n) && n > 0) return n;
    sessionStorage.setItem(startKey(sid), String(now));
  } catch { /* 저장 불가 */ }
  return now;
}

export const remainingMs = (startedAt: number, limitSec: number | null | undefined, now = Date.now()): number | null =>
  limitSec ? Math.max(0, startedAt + limitSec * 1000 - now) : null;

export function formatClock(ms: number): string {
  const s = Math.ceil(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
