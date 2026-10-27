import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { components } from "@/types/api";

export type ReportResponse = components["schemas"]["ReportResponse"];
export type ReportBody = components["schemas"]["ReportBody"];

export const reportKey = (sessionId: string) => ["report", sessionId] as const;
export const fetchReport = (sessionId: string) => apiFetch<ReportResponse>(`/api/v1/sessions/${sessionId}/report`);

/** 대기 화면: 완료/실패가 될 때까지 3초마다 폴링 */
export const useReport = (sessionId: string, poll: boolean) =>
  useQuery({ queryKey: reportKey(sessionId), queryFn: () => fetchReport(sessionId), retry: 1,
    refetchInterval: (q) => (poll && (q.state.data?.status === "queued" || q.state.data?.status === "running") ? 3000 : false) });
