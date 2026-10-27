import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { components } from "@/types/api";

type S = components["schemas"];
export type Problem = S["ProblemOut"];
export type RunOut = S["RunOut"];
export type ResultOut = S["ResultOut"];
export type CaseOut = S["CaseOut"];
export type Language = S["CodeIn"]["language"];

const base = (sid: string) => `/api/v1/sessions/${sid}/code`;
export const codeKeys = { problem: (sid: string) => ["code", "problem", sid] as const, result: (sid: string) => ["code", "result", sid] as const };

export const fetchProblem = (sid: string) => apiFetch<Problem>(`${base(sid)}/problem`);
export const runSamples = (sid: string, language: Language, source: string) => apiFetch<RunOut>(`${base(sid)}/run`, { method: "POST", json: { language, source } });
export const submitCode = (sid: string, language: Language, source: string) => apiFetch<{ submission_id: string }>(`${base(sid)}/submit`, { method: "POST", json: { language, source } });
export const fetchResult = (sid: string) => apiFetch<ResultOut>(`${base(sid)}/result`);

export const useProblem = (sid: string) => useQuery({ queryKey: codeKeys.problem(sid), queryFn: () => fetchProblem(sid), retry: false, refetchOnWindowFocus: false, staleTime: Infinity });
/** 제출 후 채점 중이면 1초마다 확인한다 (UI_SPEC §4.7). */
export const useResult = (sid: string) => useQuery({
  queryKey: codeKeys.result(sid), queryFn: () => fetchResult(sid), retry: 1,
  refetchInterval: (q) => (q.state.data?.status === "judging" ? 1000 : false),
});
