"use client";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useToastStore, type ToastKind } from "@/lib/toast";
import { cn } from "@/lib/utils";

const STYLE: Record<ToastKind, { box: string; Icon: typeof Info }> = {
  success: { box: "border-success/40 bg-success-bg text-success", Icon: CheckCircle2 },
  info: { box: "border-info/40 bg-info-bg text-info", Icon: Info },
  warning: { box: "border-warning/40 bg-warning-bg text-warning", Icon: AlertTriangle },
  error: { box: "border-danger/40 bg-danger-bg text-danger", Icon: XCircle },
};

/** 우상단 Toast 스택 (UI_SPEC §2.5). error 는 수동 닫기·assertive, 나머지는 polite. */
export function ToastViewport() {
  const { items, dismiss } = useToastStore();
  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-[min(92vw,380px)] flex-col gap-2" aria-label="알림">
      {items.map((t) => {
        const { box, Icon } = STYLE[t.kind];
        return (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"} aria-live={t.kind === "error" ? "assertive" : "polite"}
            className={cn("pointer-events-auto flex items-start gap-2 rounded border px-3 py-2.5 text-sm shadow-md", box)}>
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="break-words font-medium">{t.message}{t.count > 1 && <span className="ml-1 rounded bg-black/10 px-1 text-xs">×{t.count}</span>}</p>
              {t.requestId && <p className="mt-0.5 text-xs opacity-70">문의 시 ID: {t.requestId}</p>}
            </div>
            <button type="button" onClick={() => dismiss(t.id)} aria-label="알림 닫기" className="rounded p-0.5 hover:bg-black/10"><X className="h-4 w-4" /></button>
          </div>
        );
      })}
    </div>
  );
}
