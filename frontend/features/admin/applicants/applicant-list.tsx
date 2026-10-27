"use client";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, GitCompareArrows } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { toast } from "@/lib/toast";
import { cn, formatDateTime, score } from "@/lib/utils";
import { applicantKeys, fetchApplicants, getJob, jobKeys, type ApplicantsQuery } from "../api";
import { COMPARE_MIN, canCompare, compareHref, isComparable, toggleCompare } from "../dashboard/compare-selection";
import { PREDICTION, REPORT } from "../dashboard/dashboard-view";
import { filterApplicants, pageCount, type DecisionFilter, type ReportFilter } from "./applicant-logic";

const DECISION = { pending: "미정", pass: "합격", fail: "불합격" } as const;
const sel = "h-9 rounded border border-border bg-surface px-2 text-sm";

/**
 * ADM-04 공고별 / ADM-04b 통합 지원자 목록 (UI_SPEC §5.4). `jobId` 가 있으면 그 공고만.
 * 정렬·미검토·페이지는 서버, 이름 검색과 리포트/결정 필터는 불러온 페이지 안에서 걸러 낸다(이름이 암호화 컬럼이라 서버 검색 불가).
 * 이 목록은 면접을 마친 지원자만 보여 준다(진행 중 면접의 진행률은 제공하지 않는다).
 */
export function ApplicantList({ jobId }: { jobId?: string }) {
  const sp = useSearchParams();
  const router = useRouter();
  const job = useQuery({ queryKey: jobKeys.one(jobId ?? "none"), queryFn: () => getJob(jobId!), enabled: !!jobId, retry: 1 });
  const query: ApplicantsQuery = {
    jobId: jobId ?? sp.get("job_id") ?? undefined, review: sp.get("review") === "unreviewed" ? "unreviewed" : undefined,
    sort: sp.get("sort") === "score_desc" ? "score_desc" : "ended_at_desc", page: Math.max(1, Number(sp.get("page")) || 1),
  };
  const q = useQuery({ queryKey: applicantKeys.list(query), queryFn: () => fetchApplicants(query), retry: 1, placeholderData: (p) => p });
  const [text, setText] = useState("");
  const [report, setReport] = useState<ReportFilter>("");
  const [decision, setDecision] = useState<DecisionFilter>("");
  const [compareMode, setCompareMode] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);

  const setParam = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp.toString());
    if (v) n.set(k, v); else n.delete(k);
    if (k !== "page") n.delete("page");
    const s = n.toString();
    router.replace(s ? `?${s}` : "?", { scroll: false });
  };
  const all = q.data?.items ?? [];
  const rows = useMemo(() => filterApplicants(all, { q: text, report, decision }), [all, text, report, decision]);
  const toggle = (a: (typeof all)[number]) => { const r = toggleCompare(selected, a, all); if (r.ok) setSelected(r.ids); else toast.warning(r.message, r.reason); };
  const title = jobId ? (job.data?.title ?? "공고") : "지원자 관리";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {jobId && <Link href="/admin/jobs" className="inline-flex items-center gap-1 text-sm text-muted hover:text-text"><ArrowLeft className="h-4 w-4" aria-hidden />공고 목록</Link>}
        <h2 className="text-xl font-bold" data-testid="applicants-title">{title}{q.data && <span className="ml-2 text-sm font-normal text-muted">· 면접 완료 {q.data.total}명</span>}</h2>
        <Button variant="secondary" className="ml-auto" aria-pressed={compareMode} onClick={() => { setCompareMode((v) => !v); setSelected([]); }}><GitCompareArrows className="h-4 w-4" aria-hidden />{compareMode ? "비교 모드 해제" : "비교 모드 켜기"}</Button>
      </div>

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <label className="text-sm">이름<input value={text} onChange={(e) => setText(e.target.value)} placeholder="현재 페이지에서 검색" className={cn(sel, "block w-44")} data-testid="name-filter" /></label>
        <label className="text-sm">리포트<select value={report} onChange={(e) => setReport(e.target.value as ReportFilter)} className={cn(sel, "block")}><option value="">전체</option><option value="done">완료</option><option value="pending">생성 중</option><option value="failed">실패</option></select></label>
        <label className="text-sm">최종 결정<select value={decision} onChange={(e) => setDecision(e.target.value as DecisionFilter)} className={cn(sel, "block")}><option value="">전체</option><option value="pending">미정</option><option value="pass">합격</option><option value="fail">불합격</option></select></label>
        <label className="text-sm">정렬<select value={query.sort} onChange={(e) => setParam("sort", e.target.value === "ended_at_desc" ? null : e.target.value)} className={cn(sel, "block")} data-testid="sort"><option value="ended_at_desc">최근 면접순</option><option value="score_desc">AI 점수 높은순</option></select></label>
        <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={query.review === "unreviewed"} onChange={(e) => setParam("review", e.target.checked ? "unreviewed" : null)} />미검토만</label>
      </Card>

      {q.isError ? <Card><ErrorState message="지원자를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>
        : q.isPending ? <Skeleton className="h-64" />
        : rows.length === 0 ? <Card><EmptyState title={all.length === 0 ? "면접을 완료한 지원자가 없어요" : "조건에 맞는 지원자가 없어요"} /></Card> : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full min-w-[820px] text-sm" data-testid="applicant-table">
              <thead className="text-left text-muted"><tr>{compareMode && <th className="w-10 p-3"><span className="sr-only">비교 선택</span></th>}<th className="p-3">지원자</th>{!jobId && <th>공고</th>}<th>AI 종합점수</th><th>예상 합불(참고)</th><th>리포트</th><th>최종 결정</th><th>면접 완료</th><th><span className="sr-only">동작</span></th></tr></thead>
              <tbody>{rows.map((a) => {
                const p = PREDICTION[a.ai_pass_prediction];
                const ok = isComparable(a);
                return (
                  <tr key={a.application_id} className="border-t border-border">
                    {compareMode && <td className="p-3"><input type="checkbox" className="h-5 w-5" checked={selected.includes(a.application_id)} disabled={!ok && !selected.includes(a.application_id)} onChange={() => toggle(a)}
                      aria-label={`${a.name} 비교 선택`} title={ok ? undefined : "리포트 완료 후 비교 가능"} /></td>}
                    <td className="p-3 font-medium">{a.name}{!a.reviewed && ok && <Badge tone="warning" className="ml-1">미검토</Badge>}</td>
                    {!jobId && <td>{a.job_title}</td>}
                    <td className="tabular-nums">{score(a.ai_total_score)}</td>
                    <td><Badge tone={p.tone}>{p.label}</Badge></td>
                    <td>{REPORT[a.report_status]}</td>
                    <td><Badge tone={a.final_decision === "pass" ? "success" : a.final_decision === "fail" ? "danger" : "neutral"}>{DECISION[a.final_decision]}</Badge></td>
                    <td className="text-muted">{formatDateTime(a.interview_ended_at)}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right">
                      <Link href={`/admin/applications/${a.application_id}`} className="rounded border border-border px-2 py-1 text-xs hover:bg-surface-2">상세 보기</Link>{" "}
                      <Link href={`/admin/applications/${a.application_id}?tab=notes`} className="rounded border border-border px-2 py-1 text-xs hover:bg-surface-2">메모</Link>
                    </td>
                  </tr>);
              })}</tbody>
            </table>
          </Card>
        )}

      {q.data && pageCount(q.data.total, q.data.limit) > 1 && (
        <nav aria-label="페이지" className="flex items-center justify-center gap-2 text-sm">
          <Button variant="secondary" disabled={query.page <= 1} onClick={() => setParam("page", String(query.page - 1))}>이전</Button>
          <span className="tabular-nums" aria-live="polite">{query.page} / {pageCount(q.data.total, q.data.limit)}</span>
          <Button variant="secondary" disabled={query.page >= pageCount(q.data.total, q.data.limit)} onClick={() => setParam("page", String(query.page + 1))}>다음</Button>
        </nav>)}

      {compareMode && (
        <div className="fixed inset-x-0 bottom-0 z-30 flex items-center justify-center gap-3 border-t border-border bg-surface px-4 py-3 shadow-lg" data-testid="compare-bar">
          <span className="text-sm">선택 {selected.length}명 (같은 공고의 리포트 완료 지원자 {COMPARE_MIN}~3명)</span>
          <Link href={canCompare(selected) ? compareHref(selected) : "#"} aria-disabled={!canCompare(selected)} onClick={(e) => { if (!canCompare(selected)) e.preventDefault(); }}
            className={cn("inline-flex h-10 items-center rounded bg-primary px-4 text-sm font-semibold text-primary-fg", !canCompare(selected) && "pointer-events-none opacity-50")}>선택한 지원자 비교하기</Link>
        </div>)}
    </div>
  );
}
