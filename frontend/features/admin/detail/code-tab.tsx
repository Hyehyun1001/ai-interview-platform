"use client";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { fetchResult } from "@/features/coding/api";
import { MONACO_LANG, VERDICT_LABEL, verdictTone } from "@/features/coding/coding-logic";

const MonacoEditor = dynamic(() => import("@/features/coding/monaco-editor"), { ssr: false, loading: () => <p className="p-3 text-sm text-muted">편집기를 불러오는 중…</p> });
type Analysis = Record<string, unknown>;
const STAT_LABELS: [string, string][] = [["lines", "코드 줄 수"], ["functions", "함수 수"], ["max_function_len", "최장 함수(줄)"], ["max_complexity", "최대 복잡도"], ["lint_issues", "린트 위반"], ["maintainability", "유지보수성 지수"], ["max_nesting", "최대 중첩"], ["long_lines", "120자 초과 줄"]];

/** ADM-06 제출 코드 탭: 읽기 전용 코드 뷰어 + 판정/케이스별 결과 + 정적 분석. (AI 코드 리뷰는 아직 생성하지 않는다.) 열람은 감사 로그에 남는다. */
export function CodeTab({ sessionId }: { sessionId: string }) {
  const q = useQuery({ queryKey: ["admin", "code", sessionId], queryFn: () => fetchResult(sessionId), retry: 1, refetchOnWindowFocus: false, refetchInterval: (s) => (s.state.data?.status === "judging" ? 2000 : false) });
  if (q.isError) return <Card><ErrorState message="제출 코드를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (!q.data) return <Skeleton className="h-80" />;
  const r = q.data;
  if (r.status === "none") return <Card><EmptyState title="제출된 코드가 없어요" description="지원자가 코딩테스트를 제출하지 않았습니다. 코드 품질 항목은 점수에서 제외됩니다." /></Card>;
  if (r.status === "judging") return <Card className="p-6" aria-busy="true"><EmptyState title="채점 중이에요" description="잠시 후 자동으로 갱신됩니다." /></Card>;
  const a: Analysis = r.static_analysis ?? {};
  return (
    <div className="space-y-4" data-testid="code-tab">
      <Card className="flex flex-wrap items-center gap-3 p-4">
        <span className="text-sm">최종 판정</span><Badge tone={verdictTone(r.verdict ?? "")} data-testid="code-verdict">{r.verdict} {VERDICT_LABEL[r.verdict ?? ""]}</Badge>
        <span className="text-sm text-muted">언어 {r.language} · 최대 실행 시간 {r.runtime_ms ?? 0}ms</span>
      </Card>
      <Card className="overflow-hidden p-0">
        <div className="h-[360px]" data-testid="code-viewer"><MonacoEditor value={r.source_code ?? ""} language={MONACO_LANG[(r.language as keyof typeof MONACO_LANG) ?? "python"] ?? "plaintext"} onChange={() => undefined} readOnly /></div>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4"><h2 className="mb-2 font-semibold">케이스별 결과</h2>
          <ul className="space-y-1 text-sm">{r.cases.map((c) => <li key={c.index} className="flex items-center gap-2" data-testid="code-case"><span>케이스{c.index}</span><Badge tone={verdictTone(c.verdict)}>{c.verdict}</Badge><span className="text-xs tabular-nums text-muted">{c.runtime_ms}ms</span>{!c.visible && <span className="text-xs text-muted">비공개</span>}</li>)}</ul>
          {r.compile_log && <pre className="mt-2 max-h-32 overflow-auto rounded bg-danger-bg p-2 text-xs text-danger">{r.compile_log}</pre>}</Card>
        <Card className="p-4" data-testid="static-analysis"><h2 className="mb-2 font-semibold">정적 분석 {typeof a["tool"] === "string" && <span className="text-xs font-normal text-muted">({String(a["tool"])})</span>}</h2>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">{STAT_LABELS.filter(([k]) => a[k] != null).map(([k, l]) => <div key={k} className="contents"><dt className="text-muted">{l}</dt><dd className="tabular-nums">{String(a[k])}</dd></div>)}</dl>
          {Array.isArray(a["lint_codes"]) && a["lint_codes"].length > 0 && <p className="mt-2 text-xs text-muted">린트 규칙: {(a["lint_codes"] as string[]).join(", ")}</p>}</Card>
      </div>
    </div>
  );
}
