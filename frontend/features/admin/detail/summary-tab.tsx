"use client";
import { Badge, Card, EmptyState } from "@/components/ui/primitives";
import { cn, score } from "@/lib/utils";
import { WEIGHT_LABELS } from "../jobs/wizard-logic";
import type { ApplicationDetail, TimelineTurn } from "@/types/admin";

const LABEL = WEIGHT_LABELS as Record<string, string>;
const ORDER = Object.keys(WEIGHT_LABELS);
const sortCriteria = <T extends { criterion: string }>(xs: T[]) => [...xs].sort((a, b) => ORDER.indexOf(a.criterion) - ORDER.indexOf(b.criterion));

/** 점수 → 히트맵 배경(낮을수록 붉게, 높을수록 푸르게). 색만으로 전달하지 않도록 숫자를 함께 표시한다. */
export function heatClass(v: number | null | undefined): string {
  if (v == null) return "bg-surface-2 text-muted";
  if (v >= 80) return "bg-success-bg text-success";
  if (v >= 60) return "bg-info-bg text-info";
  if (v >= 40) return "bg-warning-bg text-warning";
  return "bg-danger-bg text-danger";
}

/** ADM-06 평가 요약 탭 (UI_SPEC §5.6.1): 종합 점수·총평, 항목별 점수(가중치), 강점/개선점 TOP3, 시선 이탈률, 질문별 점수 히트맵. AI 예상은 참고용이다. */
export function SummaryTab({ app, turns }: { app: ApplicationDetail; turns: TimelineTurn[] }) {
  const r = app.report;
  if (app.report_status === "queued" || app.report_status === "running") {
    return <Card className="p-6" aria-busy="true" data-testid="summary-pending"><EmptyState title="리포트를 생성하고 있어요" description="완료되면 자동으로 갱신됩니다. 그동안 문답 탭과 이력서는 확인할 수 있어요." /></Card>;
  }
  if (app.report_status === "failed" || !r) {
    return <Card className="p-6"><EmptyState title="평가 요약이 없어요" description={app.report_status === "failed" ? "리포트 생성에 실패했습니다. 상단의 [재생성 요청] 으로 다시 시도하세요." : "아직 평가 정보가 없습니다."} /></Card>;
  }
  const criteria = sortCriteria(r.criteria);
  const cols = criteria.map((c) => c.criterion);
  return (
    <div className="space-y-4" data-testid="summary-tab">
      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div><p className="text-xs text-muted">AI 종합점수</p><p className="text-3xl font-bold tabular-nums">{score(app.ai_total_score)}</p></div>
          <Badge tone="info">AI 예상은 참고용이에요</Badge>
          {r.scored_turns != null && <span className="text-xs text-muted">채점된 질문 {r.scored_turns}개{r.unscored_turns ? ` · 채점 제외 ${r.unscored_turns}개` : ""}</span>}
        </div>
        {r.summary && <p className="whitespace-pre-line text-sm leading-relaxed" data-testid="summary-text">{r.summary}</p>}
      </Card>

      <Card className="overflow-x-auto p-4">
        <h2 className="mb-2 font-semibold">항목별 점수</h2>
        <table className="w-full text-sm" data-testid="criteria-table">
          <thead className="text-left text-muted"><tr><th className="py-1">항목</th><th>점수</th><th>가중치</th></tr></thead>
          <tbody>{criteria.map((c) => (
            <tr key={c.criterion} className="border-t border-border">
              <td className="py-1.5">{LABEL[c.criterion] ?? c.criterion}</td>
              <td className="tabular-nums"><span className={cn("rounded px-2 py-0.5", heatClass(c.score))}>{score(c.score)}</span></td>
              <td className="tabular-nums text-muted">{c.weight != null ? `${c.weight}%` : "-"}</td>
            </tr>))}</tbody>
        </table>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Feedback title="강점 TOP3" items={r.strengths} tone="success" />
        <Feedback title="개선점 TOP3" items={r.improvements} tone="warning" />
      </div>

      <Card className="p-4" data-testid="gaze-card">
        <h2 className="mb-1 font-semibold">시선 이탈</h2>
        <p className="text-2xl font-bold tabular-nums">{r.gaze_away_ratio == null ? "-" : `${(r.gaze_away_ratio * 100).toFixed(1)}%`}</p>
        <p className="text-xs text-muted">전체 답변 시간 중 화면을 벗어난 비율{r.gaze_penalty > 0 ? ` · 점수에서 ${r.gaze_penalty}점 감점됨` : " · 점수에는 반영되지 않았어요"}</p>
      </Card>

      <Card className="overflow-x-auto p-4">
        <h2 className="mb-2 font-semibold">질문별 점수 히트맵</h2>
        {turns.every((t) => !t.review?.scores.length) ? <p className="text-sm text-muted">질문별 채점 결과가 없어요.</p> : (
          <table className="w-full text-sm" data-testid="heatmap">
            <thead className="text-left text-muted"><tr><th className="py-1">질문</th>{cols.filter((c) => c !== "code_quality").map((c) => <th key={c} className="px-1 text-center font-medium">{LABEL[c] ?? c}</th>)}</tr></thead>
            <tbody>{turns.map((t) => (
              <tr key={t.turn_id} className="border-t border-border">
                <td className="max-w-[220px] truncate py-1 pr-2" title={t.question}>{t.kind === "main" ? `Q${t.turn_no}` : t.kind === "code_followup" ? `Q${t.turn_no} 코드` : `Q${t.turn_no} 꼬리`} {t.question}</td>
                {cols.filter((c) => c !== "code_quality").map((c) => {
                  const v = t.review?.scores.find((s) => s.criterion === c)?.score;
                  return <td key={c} className="px-1 text-center"><span className={cn("inline-block min-w-10 rounded px-1.5 py-0.5 tabular-nums", heatClass(v))}>{v == null ? "-" : Math.round(v)}</span></td>;
                })}
              </tr>))}</tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function Feedback({ title, items, tone }: { title: string; items: NonNullable<ApplicationDetail["report"]>["strengths"]; tone: "success" | "warning" }) {
  return (
    <Card className="p-4">
      <h2 className="mb-2 font-semibold">{title}</h2>
      {items.length === 0 ? <p className="text-sm text-muted">항목이 없어요.</p> : (
        <ol className="space-y-3">{items.slice(0, 3).map((i) => (
          <li key={i.rank} className="text-sm"><p className="font-medium"><Badge tone={tone}>{i.rank}</Badge> {i.title}</p><p className="mt-1 text-muted">{i.detail}</p>
            {i.evidence.map((e) => <blockquote key={e.ref + e.quote} className="mt-1 border-l-2 border-border pl-2 text-xs text-muted">“{e.quote}”</blockquote>)}</li>))}</ol>
      )}
    </Card>
  );
}
