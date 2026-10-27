import type { CompareResponse } from "../api";

export const AXIS_LABELS: Record<string, string> = {
  concept_understanding: "개념 이해도", logic: "논리성", delivery: "전달력", attitude: "태도", job_expertise: "직무 전문성", code_quality: "코드 품질",
};
/** 색각 이상 대응: 색 + 마커 모양 + 선 스타일을 함께 쓴다 (UI_SPEC ADM-05) */
export const SERIES = [
  { color: "#2563eb", marker: "●", dash: "" },
  { color: "#d97706", marker: "▲", dash: "6 3" },
  { color: "#16a34a", marker: "■", dash: "2 3" },
] as const;

/** ids 쿼리 파싱: 2~3개, 중복 없음. 아니면 null (목록으로 이동) */
export function parseIds(raw: string | null): string[] | null {
  const ids = (raw ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  return ids.length >= 2 && ids.length <= 3 && new Set(ids).size === ids.length ? ids : null;
}

/** 레이더 데이터: 축마다 {axis, [지원자 id]: 점수}. 축은 서버가 정한 공통 축만 쓴다 */
export function radarData(c: CompareResponse): Record<string, string | number>[] {
  return c.axes.map((a) => ({ axis: AXIS_LABELS[a] ?? a, ...Object.fromEntries(c.applicants.map((p) => [p.application_id, p.criteria[a] ?? 0])) }));
}

/** 행별 최고점(동점은 모두) 인덱스 집합. 값이 없는 지원자는 제외 */
export function bestIndexes(values: (number | null | undefined)[]): Set<number> {
  const nums = values.filter((v): v is number => v != null);
  if (!nums.length) return new Set();
  const max = Math.max(...nums);
  return new Set(values.flatMap((v, i) => (v === max ? [i] : [])));
}
