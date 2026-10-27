"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { cn, formatDateTime, score } from "@/lib/utils";
import { adminKeys, fetchApplication, fetchTimeline } from "../api";
import { DecisionPanel, useMarkReviewed } from "./decision-panel";
import { HighlightPlayer } from "./highlight-player";
import { NotesTab } from "./notes-tab";
import { useState } from "react";
import { CodeTab } from "./code-tab";
import { ResumeTab } from "./resume-tab";
import { SummaryTab } from "./summary-tab";

const TABS = [{ id: "summary", label: "평가 요약" }, { id: "qna", label: "문답·플레이어" }, { id: "resume", label: "표준 이력서" }, { id: "code", label: "제출 코드" }, { id: "notes", label: "메모" }] as const;
type TabId = (typeof TABS)[number]["id"];

/** ADM-06 지원자 상세: 평가 요약 · 문답/플레이어 · 표준 이력서 · 제출 코드(코테 ON 공고만) · 메모. 탭은 URL `?tab=` 에 유지한다 (UI_SPEC §5.6.1). */
export function ApplicationDetailView({ applicationId }: { applicationId: string }) {
  const app = useQuery({ queryKey: adminKeys.application(applicationId), queryFn: () => fetchApplication(applicationId), retry: 1,
    refetchInterval: (q) => (q.state.data?.report_status === "queued" || q.state.data?.report_status === "running" ? 5000 : false) });  // 리포트 생성 중이면 5초마다 갱신
  const tl = useQuery({ queryKey: adminKeys.timeline(applicationId), queryFn: () => fetchTimeline(applicationId), retry: 1 });
  const sp = useSearchParams();
  const router = useRouter();
  const raw = sp.get("tab");
  const tab: TabId = TABS.some((t) => t.id === raw) ? (raw as TabId) : "summary";
  const setTab = (t: TabId) => router.replace(`?tab=${t}`, { scroll: false });
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
        {TABS.filter((t) => t.id !== "code" || a.coding_test_enabled).map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={cn("px-4 py-2 text-sm", tab === t.id ? "border-b-2 border-primary font-semibold" : "text-muted")}>{t.label}</button>)}
      </div>
      {tab === "notes" ? <NotesTab applicationId={applicationId} /> : tab === "summary" ? <SummaryTab app={a} turns={turns} /> : tab === "resume" ? <ResumeTab applicationId={applicationId} />
        : tab === "code" && a.coding_test_enabled && a.session_id ? <CodeTab sessionId={a.session_id} /> : (
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
