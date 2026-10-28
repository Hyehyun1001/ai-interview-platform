import { describe, expect, it } from "vitest";
import { bestIndexes, parseIds, radarData } from "@/features/admin/compare/compare-logic";
import { DEFAULT_WEIGHTS, buildChecklist, canPublish, cutoffBands, equalWeights, isForbiddenQuestion, lockCodeQuality, weightsDelta, weightsSum } from "@/features/admin/jobs/wizard-logic";
import type { components } from "@/types/api";

describe("weights", () => {
  it("defaults sum to 100 and delta reports what is missing", () => {
    expect(weightsSum(DEFAULT_WEIGHTS)).toBe(100);
    expect(weightsDelta({ ...DEFAULT_WEIGHTS, logic: 25 })).toBe(-5);
    expect(weightsDelta({ ...DEFAULT_WEIGHTS, logic: 10 })).toBe(10);
  });
  it("equal distribution always sums to 100, with and without coding", () => {
    for (const coding of [false, true]) {
      const w = equalWeights(coding);
      expect(weightsSum(w)).toBe(100);
      if (!coding) expect(w.code_quality).toBe(0);
    }
    expect(equalWeights(false)).toMatchObject({ concept_understanding: 20, job_expertise: 20 });
  });
  it("locking code_quality moves its share to job_expertise and keeps 100", () => {
    const w = lockCodeQuality({ ...DEFAULT_WEIGHTS, code_quality: 10, job_expertise: 20 }, false);
    expect(w.code_quality).toBe(0);
    expect(weightsSum(w)).toBe(100);
    const untouched = { ...DEFAULT_WEIGHTS, code_quality: 10, job_expertise: 20 };
    expect(lockCodeQuality(untouched, true)).toBe(untouched);
  });
});

describe("cutoff bands", () => {
  it("matches the TRD boundaries; unset gives null", () => {
    expect(cutoffBands(70, 5)).toEqual({ pass: 75, borderlineFrom: 65 });
    expect(cutoffBands(null, 5)).toBeNull();
  });
});

describe("forbidden question warning", () => {
  it.each(["결혼 계획이 있으신가요?", "나이가 어떻게 되세요", "고향이 어디세요"])("flags %s", (t) => expect(isForbiddenQuestion(t)).toBe(true));
  it.each(["나이브 베이즈를 설명해 주세요", "Redis 캐시 전략은?", "장애 대응 경험을 말씀해 주세요"])("allows %s", (t) => expect(isForbiddenQuestion(t)).toBe(false));
});

type Job = components["schemas"]["JobOut"];
const job = (over: Partial<Job> = {}): Job => ({
  id: "j", status: "draft", title: "t", job_category: "개발", industry: null, headcount: 2, deadline_at: new Date(Date.now() + 86_400_000).toISOString(), duties: "d", requirements: "r",
  preferred: null, contact_email: null, work_location: null, employment_type: null, salary_text: null, benefits: null, notice: null, answer_time_limit_sec: 120, coding_test_enabled: false, coding_test_time_limit_sec: null, updated_at: "x",
  weights: { weights: DEFAULT_WEIGHTS, gaze_penalty_enabled: false, cutoff_score: null, cutoff_margin: 5 },
  followup_rules: { max_followups: 2, trigger_ambiguous: true, trigger_contradiction: true, trigger_stt_unclear: true, guardrail_strict: true },
  questions: [], question_bank_status: "none", bank_count: 0, applicant_count: 0, ...over,
});

describe("publish checklist", () => {
  it("blocks on pool < 10 and allows at 10; missing cutoff is advice only", () => {
    const j = job();
    expect(canPublish(buildChecklist(j, 9))).toBe(false);
    const list = buildChecklist(j, 10);
    expect(canPublish(list)).toBe(true);
    expect(list.find((i) => i.key === "cutoff")).toMatchObject({ ok: false, level: "advice" });
  });
  it("requires coding time limit when coding is on, and a future deadline", () => {
    expect(canPublish(buildChecklist(job({ coding_test_enabled: true }), 10))).toBe(false);
    expect(canPublish(buildChecklist(job({ coding_test_enabled: true, coding_test_time_limit_sec: 1800 }), 10))).toBe(true);
    expect(canPublish(buildChecklist(job({ deadline_at: new Date(Date.now() - 1000).toISOString() }), 10))).toBe(false);
  });
});

describe("compare logic", () => {
  it("parseIds accepts 2-3 unique ids only", () => {
    expect(parseIds("a,b")).toEqual(["a", "b"]);
    for (const bad of [null, "", "a", "a,a", "a,b,c,d"]) expect(parseIds(bad)).toBeNull();
  });
  it("bestIndexes highlights every tied maximum and ignores nulls", () => {
    expect([...bestIndexes([80, 90, 90])]).toEqual([1, 2]);
    expect([...bestIndexes([null, 70, null])]).toEqual([1]);
    expect(bestIndexes([null, null]).size).toBe(0);
  });
  it("radarData uses only the server-provided common axes", () => {
    const data = radarData({ job_id: "j", job_title: "t", axes: ["logic"], applicants: [
      { application_id: "a", name: "가", ai_total_score: 1, ai_pass_prediction: "unavailable", criteria: { logic: 80, delivery: 50 }, gaze_away_ratio: null, strengths: [], improvements: [] },
      { application_id: "b", name: "나", ai_total_score: 1, ai_pass_prediction: "unavailable", criteria: { logic: 60 }, gaze_away_ratio: null, strengths: [], improvements: [] }] });
    expect(data).toEqual([{ axis: "논리성", a: 80, b: 60 }]);
  });
});
