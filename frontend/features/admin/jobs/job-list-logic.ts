import type { JobListOut } from "../api";

export type JobTab = "open" | "closed" | "draft";
export const TAB_LABEL: Record<JobTab, string> = { open: "진행 중", closed: "마감", draft: "임시저장" };
export const TABS: JobTab[] = ["open", "closed", "draft"];
export type JobItem = JobListOut["items"][number];

export const parseTab = (v: string | null): JobTab => (TABS.includes(v as JobTab) ? (v as JobTab) : "open");

/** 탭별 개수 (삭제된 공고는 목록에 오지 않는다). */
export const countByTab = (items: JobItem[]): Record<JobTab, number> => ({
  open: items.filter((j) => j.status === "open").length, closed: items.filter((j) => j.status === "closed").length, draft: items.filter((j) => j.status === "draft").length,
});

/** 탭 + 공고명 검색(부분 일치·대소문자 무시). 진행 중은 마감 임박순, 나머지는 최근 수정순. */
export function filterJobs(items: JobItem[], tab: JobTab, q: string): JobItem[] {
  const needle = q.trim().toLowerCase();
  const rows = items.filter((j) => j.status === tab && (!needle || j.title.toLowerCase().includes(needle)));
  const time = (iso: string | null | undefined, fallback: number) => (iso ? new Date(iso).getTime() : fallback);
  return rows.sort((a, b) => tab === "open"
    ? time(a.deadline_at, Infinity) - time(b.deadline_at, Infinity)
    : time(b.updated_at, 0) - time(a.updated_at, 0));
}

/** 삭제 확인: 공고명을 정확히 입력해야 활성화(공백 앞뒤는 무시). */
export const canConfirmDelete = (title: string, typed: string) => typed.trim() === title.trim();
