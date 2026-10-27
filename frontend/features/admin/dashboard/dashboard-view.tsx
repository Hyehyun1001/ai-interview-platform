"use client";
import { useQuery } from "@tanstack/react-query";
import { CalendarPlus, GitCompareArrows, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { JobScoreChart, MonthlyApplicantsChart } from "@/components/charts/job-score-chart";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { toast } from "@/lib/toast";
import { cn, ddayLabel, formatDateTime, score } from "@/lib/utils";
import type { AiPassPrediction, DashboardRange, DashboardResponse, RecentApplicant, ReportStatus } from "@/types/admin";
import { adminKeys, fetchDashboard } from "../api";
import { COMPARE_MIN, canCompare, compareHref, isComparable, toggleCompare } from "./compare-selection";
import { ScheduleFormDialog } from "./schedule-dialog";

const RANGES: Record<DashboardRange, string> = { "7d": "최근 7일", "30d": "최근 30일", "90d": "최근 90일" };
const PREDICTION: Record<AiPassPrediction, { label: string; tone: "success" | "warning" | "danger" | "neutral" }> = {
  likely_pass: { label: "🟢 합격권", tone: "success" }, borderline: { label: "🟡 경계", tone: "warning" },
  unlikely: { label: "🔴 미달", tone: "danger" }, unavailable: { label: "—", tone: "neutral" },
};
const REPORT: Record<ReportStatus, string> = { queued: "⏳ 대기", running: "⏳ 생성 중", done: "✅ 완료", failed: "⚠ 실패" };

function useDashboard(range: DashboardRange) {
  return useQuery({
    queryKey: adminKeys.dashboard(range), queryFn: () => fetchDashboard(range), retry: 1,
    // 리포트가 생성 중인 지원자가 있으면 15초마다 갱신해 완료를 반영한다
    refetchInterval: (q) => (q.state.data?.recent_completed_applicants.some((a) => a.report_status === "queued" || a.report_status === "running") ? 15_000 : false),
  });
}

export function DashboardView() {
  const router = useRouter();
  const [range, setRange] = useState<DashboardRange>("30d");
  const [selected, setSelected] = useState<string[]>([]);
  const [compareMode, setCompareMode] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [jobFilter, setJobFilter] = useState("");
  const lowerRef = useRef<HTMLElement>(null);
  const q = useDashboard(range);

  const enterCompareMode = () => {
    if (canCompare(selected)) { router.push(compareHref(selected)); return; }
    setCompareMode(true);
    lowerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    toast.info(`비교할 지원자를 ${COMPARE_MIN}~3명 선택하세요`);
  };

  return (
    <div className="space-y-6">
      <div className="sticky top-0 z-20 -mx-4 flex flex-wrap items-center gap-2 border-b border-border bg-bg/95 px-4 py-3 backdrop-blur">
        <Link href="/admin/jobs/new" className="inline-flex h-10 items-center gap-2 rounded bg-primary px-4 text-sm font-semibold text-primary-fg"><Plus className="h-4 w-4" aria-hidden />신규 공고 등록</Link>
        <Button variant="secondary" onClick={enterCompareMode} aria-pressed={compareMode}><GitCompareArrows className="h-4 w-4" aria-hidden />지원자 비교 모드</Button>
        <Button variant="secondary" onClick={() => setScheduleOpen(true)}><CalendarPlus className="h-4 w-4" aria-hidden />면접 일정 추가</Button>
        <label className="ml-auto flex items-center gap-2 text-sm">기간
          <select value={range} onChange={(e) => setRange(e.target.value as DashboardRange)} className="h-10 rounded border border-border bg-surface px-2">
            {Object.entries(RANGES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </div>

      {q.isPending && <DashboardSkeleton />}
      {q.isError && <Card><ErrorState message="대시보드를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>}
      {q.data && (
        <>
          <Upper data={q.data} onUnreviewed={() => { setCompareMode(false); lowerRef.current?.scrollIntoView({ behavior: "smooth" }); }} />
          <Middle data={q.data} />
          <section ref={lowerRef} aria-labelledby="lower-h" className="scroll-mt-20">
            <ApplicantTable data={q.data} compareMode={compareMode} selected={selected} setSelected={setSelected} jobFilter={jobFilter} setJobFilter={setJobFilter} />
          </section>
        </>
      )}

      {(compareMode || selected.length > 0) && (
        <div className="fixed inset-x-0 bottom-0 z-30 flex items-center justify-center gap-3 border-t border-border bg-surface px-4 py-3 shadow-lg" data-testid="compare-bar">
          <span className="text-sm">선택 {selected.length}명{selected.length < COMPARE_MIN && ` · ${COMPARE_MIN}~3명을 선택하세요`}</span>
          <Link href={canCompare(selected) ? compareHref(selected) : "#"} aria-disabled={!canCompare(selected)} onClick={(e) => { if (!canCompare(selected)) e.preventDefault(); }}
            className={cn("inline-flex h-10 items-center rounded bg-primary px-4 text-sm font-semibold text-primary-fg", !canCompare(selected) && "pointer-events-none opacity-50")}>선택한 지원자 비교하기</Link>
          <Button variant="ghost" onClick={() => { setSelected([]); setCompareMode(false); }}>취소</Button>
        </div>
      )}
      <ScheduleFormDialog open={scheduleOpen} onClose={() => setScheduleOpen(false)} />
    </div>
  );
}

function DashboardSkeleton() {
  return <div className="space-y-4" aria-busy="true" aria-label="불러오는 중"><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div><Skeleton className="h-64" /><Skeleton className="h-48" /></div>;
}

function Kpi({ label, value, sub, onClick, href }: { label: string; value: number; sub: string; onClick?: () => void; href?: string }) {
  const body = (<><p className="text-sm text-muted">{label}</p><p className="mt-1 text-3xl font-bold tabular-nums">{value}</p><p className="mt-1 text-xs text-muted">{sub}</p></>);
  const cls = "block rounded-lg border border-border bg-surface p-4 text-left shadow-sm transition hover:border-primary focus-visible:outline-2";
  return href ? <Link href={href} className={cls}>{body}</Link> : <button type="button" onClick={onClick} className={cn(cls, "w-full")}>{body}</button>;
}

function Upper({ data, onUnreviewed }: { data: DashboardResponse; onUnreviewed: () => void }) {
  const s = data.summary;
  return (
    <section aria-label="핵심 요약" className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="다가오는 면접" value={s.upcoming_interviews.total} sub={`오늘 ${s.upcoming_interviews.today} · 7일 내 ${s.upcoming_interviews.within_7d}`} href="/admin/calendar" />
        <Kpi label="진행 중 공고" value={s.open_jobs.total} sub={`코딩테스트 ON ${s.open_jobs.coding_on}`} href="/admin/jobs" />
        <Kpi label="미검토 지원자" value={s.unreviewed_applicants} sub="리포트 완료 · 미열람" onClick={onUnreviewed} />
        <Kpi label="마감 임박 공고" value={s.closing_soon_jobs} sub="3일 이내" href="/admin/jobs" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4"><h2 className="mb-2 font-semibold">직무별 평균 점수 · 합격률</h2>
          {data.stats.by_job_category.length ? <JobScoreChart stats={data.stats.by_job_category} /> : <EmptyState title="아직 집계할 면접 결과가 없어요" />}</Card>
        <Card className="p-4"><h2 className="mb-2 font-semibold">월별 지원자 수</h2>
          {data.stats.monthly_applicants.length ? <MonthlyApplicantsChart data={data.stats.monthly_applicants} /> : <EmptyState title="데이터가 없어요" />}</Card>
      </div>
    </section>
  );
}

function Middle({ data }: { data: DashboardResponse }) {
  return (
    <section aria-labelledby="mid-h" className="space-y-3">
      <div className="flex items-center justify-between"><h2 id="mid-h" className="text-lg font-semibold">공고 관리</h2><Link href="/admin/jobs" className="text-sm text-primary">전체 보기</Link></div>
      {data.recent_jobs.length === 0 ? (
        <Card><EmptyState title="등록된 공고가 없어요" action={<Link href="/admin/jobs/new" className="rounded bg-primary px-4 py-2 text-sm font-semibold text-primary-fg">신규 공고 작성</Link>} /></Card>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.recent_jobs.map((j) => {
            const d = ddayLabel(j.deadline_at);
            return (
              <li key={j.id}><Link href={`/admin/jobs/${j.id}`} className="block h-full rounded-lg border border-border bg-surface p-4 shadow-sm hover:border-primary">
                <div className="flex items-start justify-between gap-2"><h3 className="font-semibold">{j.title}</h3>
                  <Badge tone={d.tone === "closed" ? "neutral" : d.tone === "none" ? "neutral" : d.tone === "normal" ? "info" : "danger"}>{d.label}</Badge></div>
                <p className="mt-2 text-sm text-muted">지원자 {j.applicant_count}명{j.unreviewed_count > 0 && <> · <span className="font-medium text-warning">미검토 {j.unreviewed_count}</span></>}</p>
                <div className="mt-2"><Badge tone={j.coding_test_enabled ? "success" : "neutral"}>{j.coding_test_enabled ? "코테 ON" : "코테 OFF"}</Badge></div>
              </Link></li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function ApplicantTable({ data, compareMode, selected, setSelected, jobFilter, setJobFilter }:
  { data: DashboardResponse; compareMode: boolean; selected: string[]; setSelected: (s: string[]) => void; jobFilter: string; setJobFilter: (s: string) => void }) {
  const all = data.recent_completed_applicants;
  const jobs = Array.from(new Map(all.map((a) => [a.job_id, a.job_title])));
  const rows = jobFilter ? all.filter((a) => a.job_id === jobFilter) : all;
  const toggle = (a: RecentApplicant) => {
    const r = toggleCompare(selected, a, all);
    if (r.ok) setSelected(r.ids); else toast.warning(r.message, r.reason);
  };
  return (
    <Card className={cn("p-4", compareMode && "ring-2 ring-primary")}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h2 id="lower-h" className="text-lg font-semibold">최신 면접 완료 지원자</h2>
        <label className="flex items-center gap-2 text-sm">공고
          <select value={jobFilter} onChange={(e) => setJobFilter(e.target.value)} className="h-9 rounded border border-border bg-surface px-2"><option value="">전체</option>{jobs.map(([id, t]) => <option key={id} value={id}>{t}</option>)}</select></label></div>
      {rows.length === 0 ? <EmptyState title="면접을 완료한 지원자가 없어요" /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="text-left text-muted"><tr><th className="w-10 py-2"><span className="sr-only">비교 선택</span></th><th>지원자</th><th>공고</th><th>AI 종합점수</th><th>예상 합불</th><th>리포트</th><th>면접 완료</th><th><span className="sr-only">동작</span></th></tr></thead>
            <tbody>
              {rows.map((a) => {
                const p = PREDICTION[a.ai_pass_prediction];
                const ok = isComparable(a);
                const on = selected.includes(a.application_id);
                return (
                  <tr key={a.application_id} className="border-t border-border">
                    <td className="py-2"><input type="checkbox" checked={on} disabled={!ok} onChange={() => toggle(a)} aria-label={`${a.name} 비교 선택`} title={ok ? undefined : "리포트 완료 후 비교 가능"} className={cn(compareMode && "h-5 w-5")} /></td>
                    <td className="font-medium">{a.name}{!a.reviewed && ok && <Badge tone="warning" className="ml-1">미검토</Badge>}</td>
                    <td>{a.job_title}</td><td className="tabular-nums">{score(a.ai_total_score)}</td>
                    <td><Badge tone={p.tone}>{p.label}</Badge></td><td>{REPORT[a.report_status]}</td><td className="text-muted">{formatDateTime(a.interview_ended_at)}</td>
                    <td className="space-x-1 whitespace-nowrap py-2 text-right">
                      <Link href={`/admin/applications/${a.application_id}`} className="rounded border border-border px-2 py-1 text-xs hover:bg-surface-2">상세 보기</Link>
                      {ok ? <button type="button" onClick={() => toggle(a)} className="rounded border border-border px-2 py-1 text-xs hover:bg-surface-2">{on ? "선택 해제" : "비교하기"}</button> : <span className="text-xs text-muted">비교 ✕</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
