"use client";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

/** 접근 가능한 모달: ESC 닫기, 포커스 이동·복귀, Tab 순환(focus trap), 배경 클릭 닫기. */
export function Modal({ open, title, onClose, children, wide = false }: { open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const last = useRef<HTMLElement | null>(null);
  // onClose 는 보통 인라인 화살표라 렌더마다 바뀐다. 효과의 의존성에 넣으면 입력할 때마다 포커스가 첫 요소로 되돌아가므로 ref 로 최신 값만 참조한다.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    last.current = document.activeElement as HTMLElement | null;
    const root = ref.current;
    const focusables = () => Array.from(root?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])') ?? []);
    (focusables()[0] ?? root)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onCloseRef.current(); return; }
      if (e.key !== "Tab") return;
      const f = focusables();
      if (f.length === 0) return;
      const first = f[0]!, lastEl = f[f.length - 1]!;
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); last.current?.focus(); };
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} className={`my-auto max-h-[92vh] w-full overflow-y-auto rounded-lg bg-surface p-5 shadow-xl ${wide ? "max-w-3xl" : "max-w-md"}`}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="닫기" className="rounded p-1 hover:bg-surface-2"><X className="h-5 w-5" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}
