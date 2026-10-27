import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const LABELS = ["동의 완료", "이력서 제출", "장치 점검", "면접"] as const;

/** 지원 여정 단계 표시 (UI_SPEC §4.3.1). current: 1~4. 현재 단계는 aria-current="step". */
export function ApplyStepper({ current }: { current: 1 | 2 | 3 | 4 }) {
  return (
    <ol aria-label="지원 단계" className="flex flex-wrap items-center gap-2 text-sm">
      {LABELS.map((label, i) => {
        const n = i + 1, done = n < current, on = n === current;
        return (
          <li key={label} aria-current={on ? "step" : undefined} className="flex items-center gap-2">
            <span className={cn("inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold", done ? "bg-success text-white" : on ? "bg-primary text-primary-fg" : "bg-surface-2 text-muted")}>
              {done ? <Check className="h-3.5 w-3.5" aria-label="완료" /> : n}
            </span>
            <span className={cn(on ? "font-bold" : done ? "text-text" : "text-muted")}>{label}</span>
            {n < 4 && <span aria-hidden className="mx-1 h-px w-6 bg-border" />}
          </li>
        );
      })}
    </ol>
  );
}
