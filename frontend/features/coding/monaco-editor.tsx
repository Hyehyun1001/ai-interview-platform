"use client";
import Editor, { loader } from "@monaco-editor/react";

// 기본값은 jsdelivr CDN 이다. 외부 호출 금지 정책에 따라 postinstall 이 public/monaco 로 복사해 둔 로컬 번들만 쓴다.
loader.config({ paths: { vs: "/monaco/vs" } });

export default function MonacoEditor({ value, language, onChange, readOnly }: { value: string; language: string; onChange: (v: string) => void; readOnly?: boolean }) {
  return (
    <Editor
      height="100%" language={language} value={value} onChange={(v) => onChange(v ?? "")} theme="vs-dark"
      options={{ minimap: { enabled: false }, fontSize: 14, scrollBeyondLastLine: false, automaticLayout: true, readOnly, tabSize: 4, ariaLabel: "코드 편집기" }}
      loading={<p className="p-3 text-sm text-muted">편집기를 불러오는 중…</p>}
    />
  );
}
