import { describe, expect, it } from "vitest";
import { safeNext } from "@/features/auth/api";
import { ddayLabel, msToClock } from "@/lib/utils";
import { COMPARE_MAX, canCompare, compareHref, toggleCompare } from "@/features/admin/dashboard/compare-selection";
import { activeWordIndex, filterSegments, pointerToMs, segmentAt, segmentStartMs, seekByKey } from "@/features/admin/detail/player-logic";
import type { RecentApplicant, TimelineSegment } from "@/types/admin";

describe("safeNext", () => {
  it.each(["//evil.com", "/\\evil", "https://evil.com", "evil", "", null, undefined, "/a\nb"])("rejects %j", (v) => expect(safeNext(v as string, "/jobs")).toBe("/jobs"));
  it("accepts same-origin paths", () => expect(safeNext("/interview/abc?x=1", "/jobs")).toBe("/interview/abc?x=1"));
});

describe("ddayLabel", () => {
  const now = new Date(2026, 5, 10, 12, 0);
  it("computes by calendar day", () => {
    expect(ddayLabel(new Date(2026, 5, 10, 23, 0).toISOString(), now)).toEqual({ label: "D-DAY", tone: "today" });
    expect(ddayLabel(new Date(2026, 5, 11, 1, 0).toISOString(), now)).toEqual({ label: "D-1", tone: "soon" });
    expect(ddayLabel(new Date(2026, 5, 17, 9, 0).toISOString(), now)).toEqual({ label: "D-7", tone: "normal" });
  });
  it("closed once the deadline timestamp passed, even the same day", () => {
    expect(ddayLabel(new Date(2026, 5, 10, 9, 0).toISOString(), now).tone).toBe("closed");
  });
  it("none for null/invalid", () => {
    expect(ddayLabel(null).tone).toBe("none");
    expect(ddayLabel("garbage").tone).toBe("none");
  });
});

describe("msToClock", () => {
  it("formats", () => {
    expect(msToClock(0)).toBe("0:00"); expect(msToClock(65_000)).toBe("1:05"); expect(msToClock(3_725_000)).toBe("1:02:05"); expect(msToClock(-5)).toBe("0:00");
  });
});

const app = (id: string, job = "j1", report: RecentApplicant["report_status"] = "done"): RecentApplicant => ({
  application_id: id, name: id, job_id: job, job_title: job, ai_total_score: 80, ai_pass_prediction: "likely_pass", report_status: report,
  final_decision: "pending", interview_ended_at: "2026-01-01T00:00:00Z", reviewed: false,
});

describe("compare selection", () => {
  const all = [app("a"), app("b"), app("c"), app("d"), app("x", "j2"), app("r", "j1", "running")];
  it("allows up to 3 and blocks the 4th", () => {
    let sel: string[] = [];
    for (const id of ["a", "b", "c"]) { const r = toggleCompare(sel, all.find((x) => x.application_id === id)!, all); expect(r.ok).toBe(true); if (r.ok) sel = r.ids; }
    expect(sel).toHaveLength(COMPARE_MAX);
    expect(toggleCompare(sel, all[3]!, all)).toMatchObject({ ok: false, reason: "max_reached" });
  });
  it("blocks other jobs and unfinished reports, but always lets you deselect", () => {
    expect(toggleCompare(["a"], all[4]!, all)).toMatchObject({ ok: false, reason: "different_job" });
    expect(toggleCompare([], all[5]!, all)).toMatchObject({ ok: false, reason: "report_not_ready" });
    expect(toggleCompare(["a", "b"], all[0]!, all)).toEqual({ ok: true, ids: ["b"] });
  });
  it("needs 2..3 to compare; href lists ids", () => {
    expect(canCompare(["a"])).toBe(false); expect(canCompare(["a", "b"])).toBe(true); expect(canCompare(["a", "b", "c", "d"])).toBe(false);
    expect(compareHref(["a", "b"])).toBe("/admin/applicants/compare?ids=a,b");
  });
});

describe("player-logic", () => {
  const segs: TimelineSegment[] = [
    { start_ms: 0, end_ms: 5000, kind: "speech" },
    { start_ms: 10_000, end_ms: 14_000, kind: "highlight_bad", ai_comment: "x" },
    { start_ms: 20_000, end_ms: 25_000, kind: "highlight_good" },
    { start_ms: 30_000, end_ms: 31_000, kind: "stt_unclear" },
  ];
  it("filters", () => {
    expect(filterSegments(segs, "bad").map((s) => s.kind)).toEqual(["highlight_bad"]);
    expect(filterSegments(segs, "good").map((s) => s.kind)).toEqual(["highlight_good"]);
    expect(filterSegments(segs, "all")).toHaveLength(3);
  });
  it("segment playback starts 1.5s early but never below 0", () => {
    expect(segmentStartMs({ start_ms: 10_000 })).toBe(8500);
    expect(segmentStartMs({ start_ms: 500 })).toBe(0);
  });
  it("segmentAt prefers highlights on overlap", () => {
    const o: TimelineSegment[] = [{ start_ms: 0, end_ms: 100, kind: "speech" }, { start_ms: 50, end_ms: 100, kind: "highlight_bad" }];
    expect(segmentAt(o, 60)?.kind).toBe("highlight_bad");
    expect(segmentAt(o, 100)).toBeNull();
  });
  it("pointer → ms is clamped", () => {
    const rect = { left: 100, width: 200 };
    expect(pointerToMs(200, rect, 10_000)).toBe(5000); expect(pointerToMs(0, rect, 10_000)).toBe(0); expect(pointerToMs(999, rect, 10_000)).toBe(10_000);
    expect(pointerToMs(1, { left: 0, width: 0 }, 10_000)).toBe(0);
  });
  it("keyboard seek", () => {
    expect(seekByKey("ArrowRight", 1000, 60_000, segs)).toBe(6000);
    expect(seekByKey("ArrowLeft", 1000, 60_000, segs)).toBe(0);
    expect(seekByKey("]", 0, 60_000, segs)).toBe(8500);
    expect(seekByKey("]", 20_000, 60_000, segs)).toBeNull();
    expect(seekByKey("[", 30_000, 60_000, segs)).toBe(18_500);
    expect(seekByKey("x", 0, 1, segs)).toBeNull();
  });
  it("activeWordIndex", () => {
    const w = [{ w: "a", s: 0, e: 1 }, { w: "b", s: 1.2, e: 2 }];
    expect(activeWordIndex(w, 500)).toBe(0); expect(activeWordIndex(w, 1100)).toBe(-1); expect(activeWordIndex(w, 1500)).toBe(1); expect(activeWordIndex(w, 2500)).toBe(-1); expect(activeWordIndex([], 5)).toBe(-1);
  });
});
