import type { RecentApplicant } from "@/types/admin";

export const COMPARE_MAX = 3;
export const COMPARE_MIN = 2;

export type ToggleResult =
  | { ok: true; ids: string[] }
  | { ok: false; reason: "report_not_ready" | "max_reached" | "different_job"; message: string };

/** 리포트가 끝난 지원자만 비교할 수 있다 (UI_SPEC §ADM-01 비교 선택 규칙). */
export const isComparable = (a: RecentApplicant) => a.report_status === "done";

/**
 * 비교 대상 토글. 규칙: 리포트 완료만 / 최대 3명 / 같은 공고만(첫 선택 공고로 고정).
 * 이미 선택된 항목은 언제나 해제할 수 있다.
 */
export function toggleCompare(selected: string[], target: RecentApplicant, all: RecentApplicant[]): ToggleResult {
  if (selected.includes(target.application_id)) return { ok: true, ids: selected.filter((id) => id !== target.application_id) };
  if (!isComparable(target)) return { ok: false, reason: "report_not_ready", message: "리포트 완료 후 비교할 수 있어요" };
  if (selected.length >= COMPARE_MAX) return { ok: false, reason: "max_reached", message: "최대 3명까지 비교할 수 있어요" };
  const first = all.find((a) => a.application_id === selected[0]);
  if (first && first.job_id !== target.job_id) return { ok: false, reason: "different_job", message: "같은 공고의 지원자만 비교할 수 있어요" };
  return { ok: true, ids: [...selected, target.application_id] };
}

export const canCompare = (selected: string[]) => selected.length >= COMPARE_MIN && selected.length <= COMPARE_MAX;
export const compareHref = (selected: string[]) => `/admin/applicants/compare?ids=${selected.join(",")}`;
