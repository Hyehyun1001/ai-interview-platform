import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { ApplicationDetail, DashboardRange, DashboardResponse, NotificationsResponse, ScheduleCreate, SystemMetrics, TimelineResponse } from "@/types/admin";

export const adminKeys = {
  dashboard: (range: DashboardRange) => ["admin", "dashboard", range] as const,
  metrics: ["admin", "metrics"] as const,
  notifications: ["admin", "notifications"] as const,
  application: (id: string) => ["admin", "application", id] as const,
  timeline: (id: string) => ["admin", "timeline", id] as const,
};

export const fetchDashboard = (range: DashboardRange) => apiFetch<DashboardResponse>(`/api/v1/admin/dashboard?range=${range}`);
export const fetchMetrics = () => apiFetch<SystemMetrics>("/api/v1/admin/system/metrics");
export const fetchNotifications = () => apiFetch<NotificationsResponse>("/api/v1/admin/notifications");
export const createSchedule = (body: ScheduleCreate) => apiFetch<{ id: string }>("/api/v1/admin/schedules", { method: "POST", json: body });
export const fetchApplication = (id: string) => apiFetch<ApplicationDetail>(`/api/v1/admin/applications/${id}`);
export const fetchTimeline = (id: string) => apiFetch<TimelineResponse>(`/api/v1/admin/applications/${id}/timeline`);

export const useMetrics = () => useQuery({ queryKey: adminKeys.metrics, queryFn: fetchMetrics, refetchInterval: 60_000, retry: false });
export const useNotifications = () => useQuery({ queryKey: adminKeys.notifications, queryFn: fetchNotifications, refetchInterval: 30_000, retry: false });

// ── 공고 작성 마법사 · 비교 · 결정 · 메일 (OpenAPI 생성 타입 사용) ─────────────────────
import type { components } from "@/types/api";

type S = components["schemas"];
export type JobOut = S["JobOut"];
export type JobWrite = S["JobWrite"];
export type QuestionIn = S["QuestionIn"];
export type WeightsPut = S["WeightsPut"];
export type FollowupRules = S["FollowupRulesPut"];
export type BankOut = S["BankOut"];
export type JobListOut = S["JobListOut"];
export type CompareResponse = S["CompareResponse"];
export type DecisionIn = S["DecisionIn"];

const J = (method: string, json?: unknown) => ({ method, ...(json !== undefined ? { json } : {}) });

export const jobKeys = { list: ["admin", "jobs"] as const, one: (id: string) => ["admin", "job", id] as const, bank: (id: string) => ["admin", "bank", id] as const };
export const listJobs = () => apiFetch<JobListOut>("/api/v1/admin/jobs?limit=100");  // 탭별 개수는 이 목록으로 센다(최대 100건)
export const createJob = (body: JobWrite) => apiFetch<JobOut>("/api/v1/admin/jobs", J("POST", body));
export const getJob = (id: string) => apiFetch<JobOut>(`/api/v1/admin/jobs/${id}`);
export const updateJob = (id: string, body: JobWrite) => apiFetch<JobOut>(`/api/v1/admin/jobs/${id}`, J("PUT", body));
export const putQuestions = (id: string, items: QuestionIn[]) => apiFetch<S["QuestionOut"][]>(`/api/v1/admin/jobs/${id}/questions`, J("PUT", { items }));
export const putWeights = (id: string, body: WeightsPut) => apiFetch<S["WeightsOut"]>(`/api/v1/admin/jobs/${id}/weights`, J("PUT", body));
export const putFollowup = (id: string, body: FollowupRules) => apiFetch<FollowupRules>(`/api/v1/admin/jobs/${id}/followup-rules`, J("PUT", body));
export const generateBank = (id: string) => apiFetch<{ status: string }>(`/api/v1/admin/jobs/${id}/question-bank/generate`, J("POST"));
export const getBank = (id: string) => apiFetch<BankOut>(`/api/v1/admin/jobs/${id}/question-bank`);
export const publishJob = (id: string) => apiFetch<JobOut>(`/api/v1/admin/jobs/${id}/publish`, J("POST"));
export const deleteJob = (id: string) => apiFetch<void>(`/api/v1/admin/jobs/${id}`, J("DELETE"));
export const closeJob = (id: string) => apiFetch<JobOut>(`/api/v1/admin/jobs/${id}/close`, J("POST"));
export const fetchCompare = (ids: string[]) => apiFetch<CompareResponse>(`/api/v1/admin/applicants/compare?ids=${ids.join(",")}`);
export const decide = (id: string, body: DecisionIn) => apiFetch<S["DecisionOut"]>(`/api/v1/admin/applications/${id}/decision`, J("POST", body));
export const sendMail = (id: string, body: S["MailIn"]) => apiFetch<S["MailOut"]>(`/api/v1/admin/applications/${id}/mail`, J("POST", body));
export const markReviewed = (id: string) => apiFetch<void>(`/api/v1/admin/applications/${id}/reviewed`, J("POST"));
export const regenerateReport = (id: string) => apiFetch<{ report_status: string }>(`/api/v1/admin/applications/${id}/report/regenerate`, J("POST"));

// ── 메모 · 템플릿 ──
export type NoteOut = S["NoteOut"];
export type TemplateOut = S["TemplateOut"];
export const noteKeys = { list: (id: string) => ["admin", "notes", id] as const, templates: ["admin", "templates"] as const };
export const listNotes = (id: string) => apiFetch<NoteOut[]>(`/api/v1/admin/applications/${id}/notes`);
export const addNote = (id: string, body: string) => apiFetch<NoteOut>(`/api/v1/admin/applications/${id}/notes`, J("POST", { body }));
export const listTemplates = () => apiFetch<TemplateOut[]>("/api/v1/admin/job-templates");
export const createTemplate = (jobId: string, name: string) => apiFetch<TemplateOut>("/api/v1/admin/job-templates", J("POST", { job_id: jobId, name }));
export const applyTemplate = (jobId: string, templateId: string) => apiFetch<JobOut>(`/api/v1/admin/jobs/${jobId}/from-template/${templateId}`, J("POST"));

// ── 일정 · 알림 · 공고 이력 ──
export type ScheduleOut = S["ScheduleOut"];
export type JobHistoryPage = S["JobHistoryPage"];
export const scheduleKeys = { range: (from: string, to: string) => ["admin", "schedules", from, to] as const, all: ["admin", "schedules"] as const };
export const listSchedules = (from: string, to: string) => apiFetch<ScheduleOut[]>(`/api/v1/admin/schedules?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
export const updateSchedule = (id: string, body: ScheduleCreate) => apiFetch<ScheduleOut>(`/api/v1/admin/schedules/${id}`, J("PUT", body));
export const deleteSchedule = (id: string) => apiFetch<void>(`/api/v1/admin/schedules/${id}`, J("DELETE"));
export const markNotificationRead = (id: string) => apiFetch<void>(`/api/v1/admin/notifications/${id}/read`, J("POST"));
export const fetchJobHistory = (page: number) => apiFetch<JobHistoryPage>(`/api/v1/admin/job-history?page=${page}&limit=20`);

export type ApplicantPage = S["ApplicantPage"];
export interface ApplicantsQuery { jobId?: string; review?: "unreviewed"; sort: "ended_at_desc" | "score_desc"; page: number }
export const applicantKeys = { list: (q: ApplicantsQuery) => ["admin", "applicants", q] as const };
export const fetchApplicants = (q: ApplicantsQuery) => {
  const sp = new URLSearchParams({ stage: "all", sort: q.sort, page: String(q.page), limit: "20" });
  if (q.jobId) sp.set("job_id", q.jobId);
  if (q.review) sp.set("review", q.review);
  return apiFetch<ApplicantPage>(`/api/v1/admin/applications?${sp}`);
};
