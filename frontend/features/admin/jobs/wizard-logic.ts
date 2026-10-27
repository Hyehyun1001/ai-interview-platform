import type { components } from "@/types/api";

export const WEIGHT_KEYS = ["concept_understanding", "logic", "delivery", "attitude", "job_expertise", "code_quality"] as const;
export type WeightKey = (typeof WEIGHT_KEYS)[number];
export const WEIGHT_LABELS: Record<WeightKey, string> = {
  concept_understanding: "개념 이해도", logic: "논리성", delivery: "전달력", attitude: "태도", job_expertise: "직무 전문성", code_quality: "코드 품질",
};
export const DEFAULT_WEIGHTS: Record<WeightKey, number> = { concept_understanding: 25, logic: 20, delivery: 15, attitude: 10, job_expertise: 30, code_quality: 0 };
export const POOL_MIN = 10;
export const MAX_QUESTIONS = 10;

export const weightsSum = (w: Record<WeightKey, number>) => WEIGHT_KEYS.reduce((a, k) => a + (Number.isFinite(w[k]) ? w[k] : 0), 0);
/** 합계가 100 이 되려면 더 필요한(+) / 덜어야 할(−) 값 */
export const weightsDelta = (w: Record<WeightKey, number>) => 100 - weightsSum(w);

/** 코딩테스트 OFF 이면 코드 품질을 0 으로 고정하고 나머지 합이 100 이 되도록 유지한다 */
export function lockCodeQuality(w: Record<WeightKey, number>, codingEnabled: boolean): Record<WeightKey, number> {
  if (codingEnabled || w.code_quality === 0) return w;
  const rest = weightsSum({ ...w, code_quality: 0 });
  return { ...w, code_quality: 0, job_expertise: w.job_expertise + (100 - rest) };
}

/** [자동 균등 분배]: 사용 가능한 항목에 100 을 정수로 나눈다(나머지는 앞 항목부터 1 씩) */
export function equalWeights(codingEnabled: boolean): Record<WeightKey, number> {
  const keys = WEIGHT_KEYS.filter((k) => codingEnabled || k !== "code_quality");
  const base = Math.floor(100 / keys.length);
  const extra = 100 - base * keys.length;
  const out = { ...DEFAULT_WEIGHTS, code_quality: 0 } as Record<WeightKey, number>;
  for (const k of WEIGHT_KEYS) out[k] = 0;
  keys.forEach((k, i) => { out[k] = base + (i < extra ? 1 : 0); });
  return out;
}

/** 합격 기준 점수 미리보기 구간 (TRD §6.3). cutoff 미설정이면 null */
export function cutoffBands(cutoff: number | null, margin: number): { pass: number; borderlineFrom: number } | null {
  return cutoff == null ? null : { pass: cutoff + margin, borderlineFrom: cutoff - margin };
}

/** 인적 속성 질문 사전(서버 G4 와 같은 취지 — 서버가 최종 검증). 인라인 경고용 */
const FORBIDDEN = /성별|나이(?!브)|연령|몇\s*살|생년월일|결혼|미혼|기혼|배우자|자녀|임신|출산|출신지|고향|종교|가족\s*(?:관계|구성|사항)|부모님|형제|혈액형|외모/;
export const isForbiddenQuestion = (t: string) => FORBIDDEN.test(t);

export interface ChecklistItem { key: string; label: string; ok: boolean; step: 1 | 2 | 3; level: "required" | "advice" }

export function buildChecklist(job: components["schemas"]["JobOut"], poolCount: number): ChecklistItem[] {
  const w = job.weights.weights;
  const filled = !!(job.title && job.job_category && job.headcount && job.deadline_at && new Date(job.deadline_at).getTime() > Date.now() && job.duties && job.requirements);
  return [
    { key: "basic", label: "기본 정보 완료 (제목·카테고리·정원·마감일·주요 업무·지원 요건)", ok: filled, step: 1, level: "required" },
    { key: "pool", label: `질문 풀 충분 (직접 ${job.questions.length} + AI 뱅크 ${job.bank_count} ≥ ${POOL_MIN})`, ok: poolCount >= POOL_MIN, step: 2, level: "required" },
    { key: "coding", label: "코딩테스트 제한시간 지정", ok: !job.coding_test_enabled || !!job.coding_test_time_limit_sec, step: 2, level: "required" },
    { key: "weights", label: "가중치 합계 100", ok: weightsSum(w as Record<WeightKey, number>) === 100, step: 3, level: "required" },
    { key: "cutoff", label: "합격 기준 점수 설정 (미설정이면 AI 예상 합불은 \"참고 불가\")", ok: job.weights.cutoff_score != null, step: 3, level: "advice" },
  ];
}

export const canPublish = (items: ChecklistItem[]) => items.filter((i) => i.level === "required").every((i) => i.ok);
