import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

/** 밀리초 → "m:ss" (1시간 이상은 "h:mm:ss"). 음수는 0 으로 본다. */
export function msToClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export type DDayTone = "normal" | "soon" | "today" | "closed" | "none";

/** 마감 D-Day 표기 (UI_SPEC §5.1.3): D-n / D-1(주황) / D-DAY(빨강) / 마감(회색) / 임시저장은 "—". 로컬 시간대 기준 날짜 차이. */
export function ddayLabel(deadlineIso: string | null | undefined, now: Date = new Date()): { label: string; tone: DDayTone } {
  if (!deadlineIso) return { label: "—", tone: "none" };
  const d = new Date(deadlineIso);
  if (Number.isNaN(d.getTime())) return { label: "—", tone: "none" };
  if (d.getTime() < now.getTime()) return { label: "마감", tone: "closed" };  // 마감 시각이 지났으면 같은 날이어도 마감
  const dayStart = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((dayStart(d) - dayStart(now)) / 86_400_000);
  if (days === 0) return { label: "D-DAY", tone: "today" };
  if (days === 1) return { label: "D-1", tone: "soon" };
  return { label: `D-${days}`, tone: "normal" };
}

export const pct = (v: number | null | undefined, digits = 0) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
export const score = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(1));

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}
