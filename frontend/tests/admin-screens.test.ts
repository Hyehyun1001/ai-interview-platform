import { describe, expect, it } from "vitest";
import { filterApplicants, pageCount } from "@/features/admin/applicants/applicant-logic";
import { addDays, eventsOn, monthGrid, overlapping, rangeFor, sameDay, toLocalInput, weekDays, type Sched } from "@/features/admin/calendar/calendar-logic";
import { notificationHref } from "@/features/admin/history/history-logic";
import type { RecentApplicant } from "@/types/admin";

const ev = (id: string, s: string, e?: string, type = "interview1"): Sched => ({ id, title: id, type, starts_at: s, ends_at: e ?? null });

describe("캘린더 격자", () => {
  it("월 격자는 항상 일요일 시작 6주(42칸)이고 해당 월 1일~말일을 모두 덮는다", () => {
    for (const [y, m] of [[2026, 1], [2026, 9], [2025, 10], [2024, 1]] as const) {
      const g = monthGrid(y, m);
      expect(g).toHaveLength(42);
      expect(g[0]!.getDay()).toBe(0);
      const days = new Set(g.filter((d) => d.getMonth() === m).map((d) => d.getDate()));
      const last = new Date(y, m + 1, 0).getDate();
      expect(days.size).toBe(last);
    }
  });
  it("주 보기는 앵커가 속한 일~토 7일", () => {
    const w = weekDays(new Date(2026, 9, 28));  // 2026-10-28 (수)
    expect(w.map((d) => d.getDate())).toEqual([25, 26, 27, 28, 29, 30, 31]);
    expect(w[0]!.getDay()).toBe(0);
  });
  it("조회 범위: 월=격자 전체, 주=7일, 리스트=60일 (to 는 미포함)", () => {
    const a = new Date(2026, 9, 28);
    const m = rangeFor("month", a);
    expect(sameDay(m.from, monthGrid(2026, 9)[0]!)).toBe(true);
    expect(sameDay(m.to, addDays(monthGrid(2026, 9)[41]!, 1))).toBe(true);
    expect(rangeFor("week", a).to.getTime() - rangeFor("week", a).from.getTime()).toBe(7 * 86400_000);
    expect(sameDay(rangeFor("list", a).to, addDays(new Date(2026, 9, 28), 60))).toBe(true);
  });
  it("날짜별 일정은 시작 시각순", () => {
    const d = new Date(2026, 9, 28);
    const list = eventsOn([ev("b", new Date(2026, 9, 28, 15).toISOString()), ev("a", new Date(2026, 9, 28, 9).toISOString()), ev("x", new Date(2026, 9, 29, 9).toISOString())], d);
    expect(list.map((e) => e.id)).toEqual(["a", "b"]);
  });
});

describe("일정 겹침 경고", () => {
  const t = (h: number, m = 0) => new Date(2026, 9, 28, h, m).toISOString();
  const base = [ev("1차", t(10), t(11)), ev("마감", t(10), t(23), "deadline")];
  it("시간이 겹치면 찾고, 맞닿는 경계·다른 시간대·마감 일정은 겹침이 아니다", () => {
    expect(overlapping(base, { starts_at: t(10, 30), ends_at: t(11, 30) }).map((e) => e.id)).toEqual(["1차"]);
    expect(overlapping(base, { starts_at: t(11), ends_at: t(12) })).toEqual([]);
    expect(overlapping(base, { starts_at: t(9), ends_at: t(10) })).toEqual([]);
    expect(overlapping(base, { starts_at: t(14), ends_at: t(15) })).toEqual([]);
  });
  it("종료가 없으면 한 점으로 보며, 수정 중인 자기 자신은 제외한다", () => {
    expect(overlapping(base, { starts_at: t(10, 30) }).map((e) => e.id)).toEqual(["1차"]);
    expect(overlapping(base, { starts_at: t(10, 30), ends_at: t(10, 45) }, "1차")).toEqual([]);
  });
  it("datetime-local 입력 형식으로 변환한다", () => {
    expect(toLocalInput(new Date(2026, 0, 5, 9, 7).toISOString())).toBe("2026-01-05T09:07");
    expect(toLocalInput(null)).toBe("");
  });
});

const A = (over: Partial<RecentApplicant>): RecentApplicant => ({ application_id: "x", name: "김지원", job_id: "j", job_title: "백엔드", ai_total_score: 80, ai_pass_prediction: "likely_pass",
  report_status: "done", final_decision: "pending", interview_ended_at: "2026-01-01T00:00:00Z", reviewed: false, ...over }) as RecentApplicant;

describe("지원자 목록 필터", () => {
  const rows = [A({ name: "김지원" }), A({ name: "이도윤", report_status: "running", final_decision: "pass" }), A({ name: "Park Min", report_status: "failed", final_decision: "fail" })];
  it("이름은 부분·대소문자 무시, 리포트 '생성 중'은 queued/running 모두", () => {
    expect(filterApplicants(rows, { q: "도윤", report: "", decision: "" })).toHaveLength(1);
    expect(filterApplicants(rows, { q: "PARK", report: "", decision: "" })).toHaveLength(1);
    expect(filterApplicants([...rows, A({ name: "대기", report_status: "queued" })], { q: "", report: "pending", decision: "" }).map((r) => r.name)).toEqual(["이도윤", "대기"]);
  });
  it("필터는 AND 로 결합되고 비어 있으면 전부", () => {
    expect(filterApplicants(rows, { q: "", report: "", decision: "" })).toHaveLength(3);
    expect(filterApplicants(rows, { q: "", report: "failed", decision: "pass" })).toHaveLength(0);
    expect(filterApplicants(rows, { q: "", report: "done", decision: "pending" }).map((r) => r.name)).toEqual(["김지원"]);
  });
  it("페이지 수는 최소 1", () => { expect(pageCount(0)).toBe(1); expect(pageCount(20)).toBe(1); expect(pageCount(21)).toBe(2); });
});

describe("알림 이동", () => {
  it("유형별 목적지, 식별자가 없으면 안전한 기본값, 모르는 유형은 이동 없음", () => {
    expect(notificationHref("report_ready", { application_id: "a1" })).toBe("/admin/applications/a1");
    expect(notificationHref("report_ready", {})).toBeNull();
    expect(notificationHref("new_application", { job_id: "j1" })).toBe("/admin/jobs/j1/applicants");
    expect(notificationHref("new_application", null)).toBe("/admin/applicants");
    expect(notificationHref("schedule_confirmed", null)).toBe("/admin/calendar");
    expect(notificationHref("weird", { application_id: "a" })).toBeNull();
  });
});
