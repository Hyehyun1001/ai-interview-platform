import { useQuery } from "@tanstack/react-query";
import { ApiError, apiFetch, parseError } from "@/lib/api/client";
import type { components } from "@/types/api";
import type { ResumeData } from "@/features/resume/schema";

type S = components["schemas"];
export type JobSummary = S["JobSummary"];
export type JobList = S["JobList"];
export type JobDetail = S["JobDetail"];
export type MyApplication = S["MyApplication"];
export type ResumeOut = S["ResumeOut"];
export type ResumeJobOut = S["ResumeJobOut"];
export type SessionCreated = S["SessionCreated"];
export type StartResponse = S["StartResponse"];

const V1 = "/api/v1";

// ── 공고 ──
export interface JobsQuery { category: string | null; q: string; page: number; limit: number }
export const fetchJobs = (p: JobsQuery) => {
  const sp = new URLSearchParams({ page: String(p.page), limit: String(p.limit) });
  if (p.category) sp.set("category", p.category);
  if (p.q) sp.set("q", p.q);
  return apiFetch<JobList>(`${V1}/jobs?${sp}`);
};
export const useJobs = (p: JobsQuery) => useQuery({ queryKey: ["jobs", p], queryFn: () => fetchJobs(p), placeholderData: (prev) => prev, staleTime: 15_000 });

/** 상세 조회는 서버가 조회수를 +1 한다 — 포커스 복귀 같은 자동 재조회로 부풀지 않게 끈다. */
export const useJob = (id: string) =>
  useQuery({ queryKey: ["job", id], queryFn: () => apiFetch<JobDetail>(`${V1}/jobs/${id}`), retry: false, refetchOnWindowFocus: false, staleTime: 60_000 });

export const MY_APPS_KEY = ["me", "applications"] as const;
export const fetchMyApplications = () => apiFetch<MyApplication[]>(`${V1}/me/applications`);
export const useMyApplications = () => useQuery({ queryKey: MY_APPS_KEY, queryFn: fetchMyApplications, staleTime: 5_000 });

export const applyToJob = (jobId: string, consentVersion: string) =>
  apiFetch<S["ApplyResponse"]>(`${V1}/jobs/${jobId}/apply`, { method: "POST", json: { consent: true, consent_version: consentVersion } });

// ── 이력서 ──
export const RESUME_KEY = ["me", "resume"] as const;
/** 등록본이 없으면 404 RESUME_NOT_FOUND → null (오류가 아니다). */
export async function fetchMyResume(): Promise<ResumeOut | null> {
  try { return await apiFetch<ResumeOut>(`${V1}/me/resume`); } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
export const useMyResume = () => useQuery({ queryKey: RESUME_KEY, queryFn: fetchMyResume, retry: false });

export const saveMyResume = (data: ResumeData) => apiFetch<ResumeOut>(`${V1}/me/resume`, { method: "PUT", json: data });
export const confirmApplicationResume = (applicationId: string, source: "mypage" | "upload" | "manual", data?: ResumeData) =>
  apiFetch<S["ResumeSnapshotOut"]>(`${V1}/applications/${applicationId}/resume`, { method: "PUT", json: source === "mypage" ? { source } : { source, data } });
export const fetchResumeJob = (jobId: string) => apiFetch<ResumeJobOut>(`${V1}/resume-jobs/${jobId}`);

/** 업로드 진행률(%)을 알려 주기 위해 fetch 대신 XHR 을 쓴다. 인증은 쿠키(same-origin). 401 은 한 번 갱신 후 재시도한다. */
export function uploadResumePdf(file: File, onProgress: (pct: number) => void, signal: AbortSignal): Promise<{ job_id: string }> {
  const send = () => new Promise<Response>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${V1}/me/resume/upload`);
    xhr.withCredentials = true;
    xhr.responseType = "text";
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100)); };
    xhr.onload = () => resolve(new Response(xhr.responseText, { status: xhr.status, headers: { "Content-Type": "application/json" } }));
    xhr.onerror = () => reject(new Error("network"));
    signal.addEventListener("abort", () => { xhr.abort(); reject(new DOMException("aborted", "AbortError")); }, { once: true });
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
  return (async () => {
    let res = await send();
    if (res.status === 401 && (await fetch(`${V1}/auth/refresh`, { method: "POST", credentials: "include" })).ok) res = await send();
    if (!res.ok) throw await parseError(res);
    return (await res.json()) as { job_id: string };
  })();
}

// ── 세션 / 장치 점검 / 시작 ──
export const createSession = (applicationId: string) => apiFetch<SessionCreated>(`${V1}/applications/${applicationId}/session`, { method: "POST" });
export const saveDeviceCheck = (sessionId: string, devices: Record<string, string> = {}) =>
  apiFetch<S["DeviceCheckOut"]>(`${V1}/sessions/${sessionId}/device-check`, { method: "POST", json: { camera: true, mic: true, speaker: true, devices } });
export const startSession = (sessionId: string) => apiFetch<StartResponse>(`${V1}/sessions/${sessionId}/start`, { method: "POST" });
