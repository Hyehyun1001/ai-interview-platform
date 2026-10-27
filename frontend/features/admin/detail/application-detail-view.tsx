"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { cn, formatDateTime, score } from "@/lib/utils";
import { adminKeys, fetchApplication, fetchTimeline } from "../api";
import { DecisionPanel, useMarkReviewed } from "./decision-panel";
import { HighlightPlayer } from "./highlight-player";
import { NotesTab } from "./notes-tab";

const TABS = [{ id: "qna", label: "질문별 답변·음성" }, { id: "summary", label: "종합 평가" }, { id: "notes", label: "메모" }] as const;

/** ADM-06 지원자 상세. 이번 범위에서는 질문별 음성 타임라인 탭을 구현하고, 종합 평가 탭은 요약 헤더만 제공한다. */
export function ApplicationDetailView({ applicationId }: { applicationId: string }) {
  const app = useQuery({ queryKey: adminKeys.application(applicationId), queryFn: () => fetchApplication(applicationId), retry: 1,
    refetchInterval: (q) => (q.state.data?.report_status === "queued" || q.state.data?.report_status === "running" ? 5000 : false) });  // 리포트 생성 중이면 5초마다 갱신
  const tl = useQuery({ queryKey: adminKeys.timeline(applicationId), queryFn: () => fetchTimeline(applicationId), retry: 1 });
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("qna");
  const [turnIdx, setTurnIdx] = useState(0);
  useMarkReviewed(applicationId, app.data?.report_status === "done");

  if (app.isError || tl.isError) return <Card><ErrorState message="지원자 정보를 불러오지 못했어요" onRetry={() => { void app.refetch(); void tl.refetch(); }} /></Card>;
  if (app.isPending || tl.isPending) return <div className="space-y-3" aria-busy="true"><Skeleton className="h-16" /><Skeleton className="h-96" /></div>;

  const turns = tl.data.turns;
  const turn = turns[Math.min(turnIdx, turns.length - 1)];
  const a = app.data;
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-4 p-4">
        <div><h1 className="text-xl font-bold">{a.applicant_name}</h1><p className="text-sm text-muted">{a.job_title}{a.interview_ended_at && ` · ${formatDateTime(a.interview_ended_at)}`}</p></div>
        <div className="ml-auto text-right"><p className="text-xs text-muted">AI 종합점수</p><p className="text-2xl font-bold tabular-nums">{score(a.ai_total_score)}</p></div>
        <Badge tone={a.final_decision === "pass" ? "success" : a.final_decision === "fail" ? "danger" : "neutral"}>{a.final_decision === "pass" ? "합격" : a.final_decision === "fail" ? "불합격" : "결정 대기"}</Badge>
      </Card>
      <Card className="p-4"><DecisionPanel app={a} /></Card>
      <div role="tablist" className="flex gap-1 border-b border-border">
        {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={cn("px-4 py-2 text-sm", tab === t.id ? "border-b-2 border-primary font-semibold" : "text-muted")}>{t.label}</button>)}
      </div>
      {tab === "notes" ? <NotesTab applicationId={applicationId} /> : tab === "summary" ? <Card><EmptyState title="종합 평가 탭은 아직 구현되지 않았습니다" description="질문별 답변·음성 탭에서 구간별 평가를 확인할 수 있어요." /></Card> : (
        turns.length === 0 || !turn ? <Card><EmptyState title="면접 기록이 없어요" /></Card> : (
          <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
            <ol className="space-y-1" aria-label="질문 목록">
              {turns.map((t, i) => <li key={t.turn_id}><button type="button" onClick={() => setTurnIdx(i)} aria-current={i === turnIdx} className={cn("w-full rounded border border-border p-2 text-left text-sm", i === turnIdx && "border-primary bg-primary/5")}>
                <span className="text-xs text-muted">{t.kind === "main" ? `질문 ${t.turn_no}` : "꼬리질문"}</span><span className="line-clamp-2 block">{t.question}</span></button></li>)}
            </ol>
            <Card className="p-4"><h2 className="mb-3 font-semibold">{turn.question}</h2><HighlightPlayer turn={turn} />
              {turn.review && turn.review.scores.length > 0 && <ul className="mt-4 grid gap-2 sm:grid-cols-2">{turn.review.scores.map((s) => <li key={s.criterion} className="rounded bg-surface-2 p-2 text-sm"><b>{s.criterion}</b> <span className="tabular-nums">{s.score}</span>{s.comment && <p className="text-xs text-muted">{s.comment}</p>}</li>)}</ul>}
            </Card>
          </div>
        )
      )}
    </div>
  );
}
