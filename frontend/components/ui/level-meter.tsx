import { cn } from "@/lib/utils";

const HEIGHTS = [40, 72, 56, 100, 64, 88, 48];

/** 녹음 레벨 미터 (시그니처). live=true 일 때만 움직이고, 그 외에는 고정된 막대다. */
export function LevelMeter({ live = false, className }: { live?: boolean; className?: string }) {
  return (
    <span aria-hidden className={cn("inline-flex h-4 items-end gap-0.5", className)}>
      {HEIGHTS.map((h, i) => (
        <span key={i} className={cn("w-0.5 rounded-sm bg-current", live && "animate-pulse")}
          style={{ height: `${h}%`, animationDelay: live ? `${i * 120}ms` : undefined }} />
      ))}
    </span>
  );
}
