"use client";
import { X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * 오른쪽에서 열리는 사이드 패널. ESC·배경 클릭으로 닫고, 열려 있는 동안 Tab 이 패널 안에서만 돌며(focus trap),
 * 닫으면 열었던 버튼으로 포커스가 돌아온다. 본문 스크롤은 잠그고, 모션 감소 설정이면 애니메이션을 생략한다.
 * onClose 는 보통 인라인 화살표라 ref 로만 참조한다(효과 의존성에 넣으면 입력할 때마다 포커스가 튄다).
 */
export function Drawer({ open, title, onClose, children, footer, widthClass = "max-w-[34rem]" }: {
  open: boolean; title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; widthClass?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const last = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!open) { setShown(false); return; }
    last.current = document.activeElement as HTMLElement | null;
    const id = requestAnimationFrame(() => setShown(true));  // 마운트 직후 한 프레임 뒤에 슬라이드 인
    const root = panel.current;
    const focusables = () => Array.from(root?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])') ?? []);
    // 첫 포커스는 패널 자체(제목이 읽힌다). 첫 버튼에 두면 열 때마다 닫기 버튼에 포커스 링이 크게 보인다.
    (root?.querySelector<HTMLElement>("[data-autofocus]") ?? root)?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (document.querySelector('[role="dialog"][aria-modal="true"]:not([data-drawer])')) return;  // 위에 모달이 열려 있으면 모달이 먼저 닫힌다
        e.stopPropagation(); onCloseRef.current(); return;
      }
      if (e.key !== "Tab") return;
      const f = focusables();
      if (f.length === 0) return;
      const first = f[0]!, lastEl = f[f.length - 1]!;
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      cancelAnimationFrame(id);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      last.current?.focus();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40" data-testid="drawer-root">
      <div className={cn("absolute inset-0 bg-black/40 transition-opacity duration-200 motion-reduce:transition-none", shown ? "opacity-100" : "opacity-0")} onMouseDown={() => onCloseRef.current()} aria-hidden />
      <div ref={panel} role="dialog" aria-modal="true" data-drawer aria-labelledby="drawer-title" tabIndex={-1}
        className={cn("absolute inset-y-0 right-0 flex w-full flex-col bg-surface shadow-2xl outline-none focus-visible:outline-none transition-transform duration-200 ease-out motion-reduce:transition-none", widthClass, shown ? "translate-x-0" : "translate-x-full")}>
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-5 py-4">
          <div id="drawer-title" className="min-w-0 flex-1">{title}</div>
          <button type="button" onClick={() => onCloseRef.current()} aria-label="닫기" className="rounded p-2 hover:bg-surface-2"><X className="h-5 w-5" aria-hidden /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="shrink-0 border-t border-border px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}
