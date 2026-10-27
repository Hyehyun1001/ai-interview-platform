/** 일정 캘린더 순수 로직 (ADM-07). 날짜 계산은 브라우저 로컬 시간대 기준이다. */
export interface Sched { id: string; title: string; type: string; job_id?: string | null; application_id?: string | null; starts_at: string; ends_at?: string | null }

export const TYPE_LABEL: Record<string, string> = { interview1: "1차 면접", interview2: "2차 면접", doc_screen: "서류 검토", deadline: "마감" };

export const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
export const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** 달력 격자: 해당 월을 포함하는 주(일~토) 단위 6주(42칸)로 고정해 높이가 달라지지 않게 한다. */
export function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const start = addDays(first, -first.getDay());
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}
export const weekDays = (anchor: Date): Date[] => { const s = addDays(startOfDay(anchor), -anchor.getDay()); return Array.from({ length: 7 }, (_, i) => addDays(s, i)); };

/** 조회 범위(from 포함, to 미포함)의 ISO 문자열. 월 보기는 격자 전체를 덮는다. */
export function rangeFor(view: "month" | "week" | "list", anchor: Date): { from: Date; to: Date } {
  if (view === "month") { const g = monthGrid(anchor.getFullYear(), anchor.getMonth()); return { from: g[0]!, to: addDays(g[41]!, 1) }; }
  if (view === "week") { const w = weekDays(anchor); return { from: w[0]!, to: addDays(w[6]!, 1) }; }
  return { from: startOfDay(anchor), to: addDays(startOfDay(anchor), 60) };  // 리스트: 오늘부터 60일
}

export const eventsOn = (events: Sched[], day: Date): Sched[] => events.filter((e) => sameDay(new Date(e.starts_at), day)).sort((a, b) => a.starts_at.localeCompare(b.starts_at));

const endOf = (e: Pick<Sched, "starts_at" | "ends_at">) => new Date(e.ends_at ?? e.starts_at).getTime();
/** 시간이 겹치는 다른 일정 (경고용, 저장은 막지 않는다). 종료가 없으면 시작 시각 한 점으로 본다. 맞닿는 경계는 겹침이 아니다. */
export function overlapping(events: Sched[], cand: { starts_at: string; ends_at?: string | null }, ignoreId?: string): Sched[] {
  const s = new Date(cand.starts_at).getTime(), e = endOf(cand);
  return events.filter((o) => {
    if (o.id === ignoreId || o.type === "deadline") return false;
    const os = new Date(o.starts_at).getTime(), oe = endOf(o);
    return e > os && s < oe || (s === e && s >= os && s < oe) || (os === oe && os >= s && os < e);
  });
}

export const toLocalInput = (iso?: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};
export const isPast = (iso: string, now = Date.now()) => new Date(iso).getTime() < now;
