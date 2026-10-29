"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";

/** 임시 저장 주기. 마지막 입력이 아니라 **처음 저장되지 않은 변경 시점부터** 센다(계속 타이핑해도 이 주기마다 저장). E2E 는 짧게 줄인다. */
export const AUTOSAVE_MS = Number(process.env.NEXT_PUBLIC_AUTOSAVE_MS) > 0 ? Number(process.env.NEXT_PUBLIC_AUTOSAVE_MS) : 30_000;

export type AutosavePhase = "idle" | "saving" | "saved" | "error" | "stale";
export interface AutosaveInfo {
  phase: AutosavePhase; dirty: boolean; enabled: boolean; canSave: boolean; savedAt: Date | null; saveNow: () => Promise<boolean>;
}

const hhmm = (d: Date) => d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });

/** 헤더에 보여 줄 한 줄 상태. 어떤 상태에서도 "저장된 것"과 "아직 저장되지 않은 것"이 구분되게 한다. */
export function autosaveLabel(i: Pick<AutosaveInfo, "phase" | "dirty" | "enabled" | "canSave" | "savedAt">): { text: string; tone: "muted" | "warning" | "danger" | "success" } {
  if (i.phase === "stale") return { text: "다른 곳에서 수정되어 자동 저장을 멈췄어요. 새로고침해 주세요", tone: "danger" };
  if (i.phase === "saving") return { text: "자동 저장 중…", tone: "muted" };
  if (i.phase === "error" && i.dirty) return { text: "자동 저장에 실패했어요. 곧 다시 시도합니다", tone: "danger" };
  if (i.dirty) {
    if (!i.enabled) return { text: "저장되지 않은 변경 사항이 있어요", tone: "warning" };  // 게시된 공고 등은 자동 저장하지 않는다
    if (!i.canSave) return { text: "필수 입력을 채우면 자동 저장돼요 · 저장되지 않은 변경 사항이 있어요", tone: "warning" };
    return { text: "저장되지 않은 변경 사항이 있어요 · 곧 자동 저장", tone: "warning" };
  }
  return i.savedAt ? { text: `자동 저장됨 ${hhmm(i.savedAt)}`, tone: "success" } : { text: "", tone: "muted" };
}

/**
 * 입력 상태(`signature`)가 마지막 저장본과 달라지면 `delayMs` 뒤에 `save` 를 호출한다.
 * 저장 중 입력이 더 바뀌면 끝난 뒤 다시 예약한다. 실패하면 같은 주기로 재시도하고, 다른 곳에서 수정된 경우(STALE_UPDATE)는 멈춘다(덮어쓰지 않는다).
 * `enabled=false`(게시된 공고 등)면 저장하지 않고 변경 여부만 알린다. `canSave=false`(필수 입력 미충족)면 기다린다.
 */
export function useAutosave({ signature, enabled, canSave, save, delayMs = AUTOSAVE_MS }: {
  signature: string; enabled: boolean; canSave: boolean; save: () => Promise<unknown>; delayMs?: number;
}): AutosaveInfo & { markSaved: () => void } {
  const [baseline, setBaseline] = useState(signature);
  const [phase, setPhase] = useState<AutosavePhase>("idle");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const sigRef = useRef(signature);
  sigRef.current = signature;
  const saveRef = useRef(save);
  saveRef.current = save;
  const busy = useRef(false);
  const dirty = signature !== baseline;

  const saveNow = useCallback(async (): Promise<boolean> => {
    if (busy.current) return false;
    busy.current = true;
    const started = sigRef.current;
    setPhase("saving");
    try {
      await saveRef.current();
      setBaseline(started);
      setSavedAt(new Date());
      setPhase("saved");
      return true;
    } catch (e) {
      setPhase(e instanceof ApiError && e.code === "STALE_UPDATE" ? "stale" : "error");
      return false;
    } finally { busy.current = false; }
  }, []);

  useEffect(() => {
    if (!enabled || !dirty || !canSave || phase === "stale" || phase === "saving") return;
    const t = setTimeout(() => void saveNow(), delayMs);
    return () => clearTimeout(t);
  }, [enabled, dirty, canSave, phase, delayMs, saveNow]);

  /** 사용자가 직접 저장했을 때: 현재 입력을 저장본으로 본다. */
  const markSaved = useCallback(() => { setBaseline(sigRef.current); setSavedAt(new Date()); setPhase("saved"); }, []);
  return { phase, dirty, enabled, canSave, savedAt, saveNow, markSaved };
}

// ── 새 공고(아직 서버에 없음)의 입력 백업 ─────────────────────────────────────────────
const NEW_KEY = "ai-interview:job-draft:new";
export interface JobBackup<T> { form: T; savedAt: string }

export function readNewJobBackup<T>(): JobBackup<T> | null {
  try { const raw = localStorage.getItem(NEW_KEY); return raw ? (JSON.parse(raw) as JobBackup<T>) : null; } catch { return null; }
}
export function writeNewJobBackup<T>(form: T): void {
  try { localStorage.setItem(NEW_KEY, JSON.stringify({ form, savedAt: new Date().toISOString() } satisfies JobBackup<T>)); } catch { /* 저장소를 못 쓰는 환경 */ }
}
export function clearNewJobBackup(): void {
  try { localStorage.removeItem(NEW_KEY); } catch { /* 무시 */ }
}
