"use client";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

/** 접근 가능한 모달: ESC 닫기, 포커스 이동·복귀, Tab 순환(focus trap), 배경 클릭 닫기. */
export function Modal({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const last = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    last.current = document.activeElement as HTMLElement | null;
    const root = ref.current;
    const focusables = () => Array.from(root?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])') ?? []);
    (focusables()[0] ?? root)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
      if (e.key !== "Tab") return;
      const f = focusables();
      if (f.length === 0) return;
      const first = f[0]!, lastEl = f[f.length - 1]!;
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); last.current?.focus(); };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} className="w-full max-w-md rounded-lg bg-surface p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="닫기" className="rounded p-1 hover:bg-surface-2"><X className="h-5 w-5" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}
