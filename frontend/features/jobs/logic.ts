import type { components } from "@/types/api";

export type MyApplication = components["schemas"]["MyApplication"];

export const CONSENT_VERSION = "2026-01";
export const PAGE_SIZE = 12;
/** UI_SPEC §4.2.1 직무 카테고리. 서버는 job_category 문자열 일치로 거른다. */
export const CATEGORIES = ["개발", "디자인", "기획", "마케팅", "영업"] as const;

/** 지원 단계별 "이어서 하기" 목적지 (UI_SPEC §4.2.2). */
export function continueTarget(app: Pick<MyApplication, "application_id" | "status" | "session_id" | "result" | "report_status">): { label: string; href: string } {
  const id = app.application_id, sid = app.session_id;
  switch (app.status) {
    case "applied": return { label: "이어서 진행하기", href: `/apply/${id}/resume` };
    case "prepared": return { label: "장치 점검으로 이동", href: `/apply/${id}/device-check` };
    case "interviewing": return sid ? { label: "면접 이어하기", href: `/interview/${sid}` } : { label: "장치 점검으로 이동", href: `/apply/${id}/device-check` };
    case "interview_done": return sid ? { label: "리포트 생성 중", href: `/interview/${sid}/waiting` } : { label: "이어서 진행하기", href: `/apply/${id}/resume` };
    case "report_ready": return sid ? { label: "리포트 보기", href: `/reports/${sid}` } : { label: "이어서 진행하기", href: `/apply/${id}/resume` };
  }
}

export const totalPages = (total: number, limit = PAGE_SIZE): number => Math.max(1, Math.ceil(total / limit));

/** URL 쿼리 → 목록 조건. 잘못된 값(음수/NaN 페이지, 알 수 없는 카테고리)은 기본값으로 되돌려 URL 이 단일 진실 원천이 되게 한다. */
export function parseJobsQuery(sp: { get(k: string): string | null }): { category: string | null; q: string; page: number } {
  const cat = sp.get("category");
  const page = Number.parseInt(sp.get("page") ?? "1", 10);
  return {
    category: cat && (CATEGORIES as readonly string[]).includes(cat) ? cat : null,
    q: (sp.get("q") ?? "").trim().slice(0, 100),
    page: Number.isFinite(page) && page >= 1 ? page : 1,
  };
}

export function buildJobsHref(p: { category?: string | null; q?: string; page?: number }): string {
  const sp = new URLSearchParams();
  if (p.category) sp.set("category", p.category);
  if (p.q && p.q.trim()) sp.set("q", p.q.trim());
  if (p.page && p.page > 1) sp.set("page", String(p.page));
  const s = sp.toString();
  return s ? `/jobs?${s}` : "/jobs";
}

export const isDeadlinePassed = (deadlineIso: string | null | undefined, now: Date = new Date()): boolean =>
  !!deadlineIso && new Date(deadlineIso).getTime() <= now.getTime();

export function formatDeadline(iso: string | null | undefined): string {
  if (!iso) return "상시 모집";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : `~ ${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

/** 마이페이지 지원 현황의 상태 라벨 (UI_SPEC §4.4.1). */
export const STATUS_LABEL: Record<MyApplication["status"], string> = {
  applied: "이력서 제출 대기", prepared: "장치 점검 대기", interviewing: "면접 진행 중", interview_done: "리포트 생성 중", report_ready: "리포트 완료",
};

/** 공고 본문(담당자가 입력한 줄글)을 항목 목록으로. 줄 앞의 "-", "•", "·", "*" 표시는 떼고 빈 줄은 버린다. */
export function toBullets(text: string | null | undefined): string[] {
  return (text ?? "").split(/\r?\n/).map((l) => l.trim().replace(/^[-•·*▪●]\s*/, "")).filter(Boolean);
}

/**
 * 답변 시간 기준 "최대" 면접 소요 시간(분). 모든 질문에 제한시간을 꽉 채워 답하고 꼬리질문도 최대 횟수만큼 나오는 경우의 상한이다.
 * 실제 소요 시간의 예측이 아니므로 화면에는 "최대"로 표기한다. 필요한 값이 없으면 null.
 */
export function maxInterviewMinutes(questions: number | null | undefined, followups: number | null | undefined, answerSec: number | null | undefined): number | null {
  if (!questions || !answerSec) return null;
  return Math.ceil((questions * (1 + (followups ?? 0)) * answerSec) / 60);
}

export const EMPLOYMENT_LABEL: Record<string, string> = { regular: "정규직", contract: "계약직", intern: "인턴", parttime: "파트타임" };
export const EMPLOYMENT_OPTIONS = Object.entries(EMPLOYMENT_LABEL) as [string, string][];
