import type { RecentApplicant } from "@/types/admin";

export type DecisionFilter = "" | "pending" | "pass" | "fail";
export type ReportFilter = "" | "done" | "pending" | "failed";
export interface Filters { q: string; report: ReportFilter; decision: DecisionFilter }

/** 서버가 이름(암호화 컬럼)으로 검색할 수 없어, 불러온 페이지 안에서만 걸러 낸다. */
export function filterApplicants(rows: RecentApplicant[], f: Filters): RecentApplicant[] {
  const q = f.q.trim().toLowerCase();
  return rows.filter((a) => {
    if (q && !a.name.toLowerCase().includes(q)) return false;
    if (f.report === "done" && a.report_status !== "done") return false;
    if (f.report === "pending" && a.report_status !== "queued" && a.report_status !== "running") return false;
    if (f.report === "failed" && a.report_status !== "failed") return false;
    if (f.decision && a.final_decision !== f.decision) return false;
    return true;
  });
}

export const pageCount = (total: number, limit = 20) => Math.max(1, Math.ceil(total / limit));
