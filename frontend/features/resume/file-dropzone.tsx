"use client";
import { Upload } from "lucide-react";
import { useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";
import { validatePdfFile } from "./schema";

/**
 * PDF 드롭존 (UI_SPEC §4.3.3). 비PDF·10MB 초과는 업로드 요청을 보내지 않고 인라인 오류만 보여 준다.
 * 전체가 버튼 역할이라 Enter/Space 로도 파일 선택을 열 수 있다. 파일은 1개만 받는다.
 */
export function FileDropzone({ onFile, disabled }: { onFile: (f: File) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function accept(files: FileList | File[] | null | undefined) {
    const f = files?.[0];
    if (!f) return;
    const msg = validatePdfFile(f);
    setError(msg);
    if (!msg) onFile(f);
  }
  const open = () => { if (!disabled) input.current?.click(); };
  const onKey = (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); if (!disabled) accept(e.dataTransfer.files); };

  return (
    <div>
      <div role="button" tabIndex={disabled ? -1 : 0} aria-disabled={disabled} aria-describedby="dz-help" data-testid="dropzone"
        onClick={open} onKeyDown={onKey} onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}
        className={cn("flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed p-8 text-center transition",
          over ? "border-primary bg-info-bg" : "border-border hover:bg-surface-2", disabled && "cursor-not-allowed opacity-50")}>
        <Upload className="h-6 w-6 text-muted" aria-hidden />
        <p className="text-sm font-medium">PDF 파일을 끌어다 놓거나 <span className="text-primary underline">파일 선택</span></p>
        <p id="dz-help" className="text-xs text-muted">PDF만 가능 · 최대 10MB / 20쪽</p>
        <span className="sr-only" aria-live="polite">{over ? "여기에 놓으면 업로드합니다" : ""}</span>
      </div>
      <input ref={input} type="file" accept="application/pdf,.pdf" className="sr-only" tabIndex={-1} aria-label="PDF 파일 선택" data-testid="pdf-input"
        onChange={(e) => { accept(e.target.files); e.target.value = ""; }} />
      {error && <p role="alert" data-testid="dropzone-error" className="mt-2 text-sm text-danger">{error}</p>}
    </div>
  );
}
