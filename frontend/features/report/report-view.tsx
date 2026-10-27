"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { pct, score } from "@/lib/utils";
import { AXIS_LABELS } from "@/features/admin/compare/compare-logic";
import { useReport, type ReportBody } from "./api";

type Item = ReportBody["strengths"][number];

function Feedback({ title, items }: { title: string; items: Item[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section><h2 className="mb-2 font-semibold">{title}</h2>
      <ol className="space-y-2">{items.map((it, i) => (
        <li key={it.rank} className="rounded border border-border p-3 text-sm"><p className="font-medium">{it.rank}. {it.title}</p><p className="text-muted">{it.detail}</p>
          {it.evidence.length > 0 && <><button type="button" className="mt-1 text-xs text-primary" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>근거 {open === i ? "▴" : "▾"}</button>
            {open === i && <ul className="mt-1 list-disc pl-5 text-xs">{it.evidence.map((e) => <li key={e.quote}>“{e.quote}”</li>)}</ul>}</>}</li>))}</ol></section>
  );
}

/** APP-09: 최종 피드백 리포트. AI 예상 합불·가중치는 API 가 주지 않으며 화면에도 없다. */
export function ReportView({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const q = useReport(sessionId, false);
  const r = q.data;
  useEffect(() => { if (r && r.status !== "done") router.replace(`/interview/${sessionId}/waiting`); }, [r, router, sessionId]);
  if (q.isPending) return <Skeleton className="h-96" />;
  if (q.isError) return <Card><ErrorState message="리포트를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  const rep = r?.report;
  if (!rep) return null;
  const radar = rep.criteria.filter((c) => c.criterion in AXIS_LABELS).map((c) => ({ axis: AXIS_LABELS[c.criterion]!, score: c.score }));
  return (
    <article className="space-y-4" data-testid="report">
      <h1 className="text-xl font-bold">면접 피드백 리포트</h1>
      {rep.degraded_mode && <p role="status" className="rounded bg-info-bg p-3 text-sm text-info">일부 구간이 간소화된 방식으로 진행되었어요.</p>}
      <Card className="flex flex-wrap items-center gap-6 p-5"><div><p className="text-sm text-muted">종합 점수</p><p className="text-4xl font-bold tabular-nums" data-testid="total-score">{score(rep.total_score)}</p></div>
        <p className="min-w-[16rem] flex-1 text-sm leading-relaxed">{rep.summary}</p></Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4"><h2 className="mb-2 font-semibold">항목별 점수</h2>
          <div className="h-64" role="img" aria-label={`항목별 점수: ${radar.map((r2) => `${r2.axis} ${r2.score}`).join(", ")}`}><ResponsiveContainer width="100%" height="100%"><RadarChart data={radar}><PolarGrid /><PolarAngleAxis dataKey="axis" /><PolarRadiusAxis domain={[0, 100]} /><Radar dataKey="score" stroke="#2563eb" fill="#2563eb" fillOpacity={0.25} /></RadarChart></ResponsiveContainer></div>
          <ul className="mt-2 space-y-1 text-sm">{rep.criteria.map((c) => <li key={c.criterion} className="flex justify-between"><span>{AXIS_LABELS[c.criterion] ?? c.criterion}</span><span className="tabular-nums">{c.score.toFixed(0)}</span></li>)}</ul></Card>
        <Card className="space-y-4 p-4"><Feedback title="강점 TOP" items={rep.strengths} /><Feedback title="개선점 TOP" items={rep.improvements} /></Card>
      </div>
      <Card className="p-4"><h2 className="mb-2 font-semibold">질문별 피드백</h2>
        {rep.turns.map((t) => (<details key={t.turn_no} className="border-t border-border py-2 text-sm print:open"><summary className="cursor-pointer font-medium">{t.turn_no}. {t.question}</summary>
          {t.answer_text ? <p className="mt-2 rounded bg-surface-2 p-2">{t.answer_text}</p> : <p className="mt-2 text-muted">보관 기간이 지나 답변 텍스트가 삭제되었습니다.</p>}
          {t.scores.length === 0 ? <p className="mt-2 text-muted">평가 정보 없음</p> : <ul className="mt-2 space-y-1">{t.scores.map((s) => <li key={s.criterion}><b>{AXIS_LABELS[s.criterion] ?? s.criterion} {s.score.toFixed(0)}</b> — {s.comment}
            {s.evidence.length > 0 && <span className="text-xs text-muted"> (근거: “{s.evidence[0]!.quote}”)</span>}</li>)}</ul>}</details>))}</Card>
      <Card className="p-4 text-sm"><h2 className="mb-1 font-semibold">시선 분석</h2>{rep.gaze_away_ratio == null ? "기록이 없어요." : <>시선 이탈 비율 {pct(rep.gaze_away_ratio, 1)} (참고 지표입니다)</>}
        <p className="mt-1 text-xs text-muted">ⓘ 이 수치는 면접 환경에 따라 달라질 수 있으며 부정행위 판단 기준이 아닙니다.</p></Card>
      <div className="flex justify-end gap-2 print:hidden"><Button variant="secondary" onClick={() => window.print()}>인쇄/PDF 저장</Button><Link href="/jobs" className="inline-flex h-10 items-center rounded border border-border px-4 text-sm">공고 목록</Link></div>
    </article>
  );
}
