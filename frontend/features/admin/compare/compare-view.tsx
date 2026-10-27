"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip } from "recharts";
import { Badge, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { cn, pct, score } from "@/lib/utils";
import { fetchCompare } from "../api";
import { AXIS_LABELS, SERIES, bestIndexes, parseIds, radarData } from "./compare-logic";

const PRED = { likely_pass: "🟢 합격권", borderline: "🟡 경계", unlikely: "🔴 미달", unavailable: "—" } as const;

export function CompareView() {
  const router = useRouter();
  const ids = parseIds(useSearchParams().get("ids"));
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const q = useQuery({ queryKey: ["admin", "compare", ids], queryFn: () => fetchCompare(ids!), enabled: !!ids, retry: false });

  useEffect(() => {
    if (!ids) { toast.warning("비교할 지원자를 2~3명 선택해 주세요"); router.replace("/admin"); }
  }, [ids, router]);
  useEffect(() => {
    const e = q.error;
    if (!(e instanceof ApiError)) return;
    if (e.code === "COMPARE_INVALID_SELECTION") { toast.warning("같은 공고의 지원자 2~3명만 비교할 수 있어요"); router.replace("/admin"); }
    else if (e.code === "REPORT_NOT_READY") { toast.warning("리포트가 완료되지 않은 지원자가 있어요"); router.replace("/admin"); }
  }, [q.error, router]);

  const data = q.data;
  const rows = useMemo(() => (data ? radarData(data) : []), [data]);
  if (!ids) return null;
  if (q.isPending) return <Skeleton className="h-96" />;
  if (q.isError || !data) return <Card><ErrorState message="비교 데이터를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  const P = data.applicants;
  const rowDefs: { label: string; vals: (number | null)[]; fmt: (v: number | null) => string }[] = [
    { label: "AI 종합 점수", vals: P.map((p) => p.ai_total_score), fmt: score },
    ...Object.keys(AXIS_LABELS).filter((a) => P.some((p) => a in p.criteria)).map((a) => ({ label: AXIS_LABELS[a]!, vals: P.map((p) => p.criteria[a] ?? null), fmt: (v: number | null) => (v == null ? "—" : v.toFixed(0)) })),
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><Link href="/admin" className="text-sm text-primary">← 대시보드</Link>
        <h1 className="text-xl font-bold">지원자 비교 ({P.length}명) · {data.job_title}</h1></div>
      <Card className="p-4">
        <div className="mb-2 flex flex-wrap gap-3" role="group" aria-label="범례">{P.map((p, i) => { const s = SERIES[i]!; const off = hidden.has(p.application_id); return (
          <button key={p.application_id} type="button" aria-pressed={!off} onClick={() => setHidden((h) => { const n = new Set(h); if (off) n.delete(p.application_id); else n.add(p.application_id); return n; })}
            className={cn("rounded border border-border px-2 py-1 text-sm", off && "opacity-40 line-through")}><span style={{ color: s.color }} aria-hidden>{s.marker}</span> {p.name}</button>); })}</div>
        <div className="h-80" role="img" aria-label={`항목별 점수 비교: ${P.map((p) => `${p.name} ${data.axes.map((a) => `${AXIS_LABELS[a]} ${p.criteria[a]}`).join(", ")}`).join(" / ")}`}>
          <ResponsiveContainer width="100%" height="100%"><RadarChart data={rows}><PolarGrid /><PolarAngleAxis dataKey="axis" /><PolarRadiusAxis domain={[0, 100]} />
            {P.map((p, i) => hidden.has(p.application_id) ? null : <Radar key={p.application_id} name={p.name} dataKey={p.application_id} stroke={SERIES[i]!.color} fill={SERIES[i]!.color} fillOpacity={0.12} strokeDasharray={SERIES[i]!.dash} />)}
            <Tooltip /></RadarChart></ResponsiveContainer></div>
      </Card>
      <Card className="overflow-x-auto"><table className="w-full min-w-[560px] text-sm" data-testid="compare-table">
        <caption className="sr-only">지원자 요약 비교 표</caption>
        <thead><tr><th scope="col" className="sticky left-0 bg-surface p-3 text-left">항목</th>{P.map((p, i) => <th key={p.application_id} scope="col" className="p-3 text-left"><span style={{ color: SERIES[i]!.color }} aria-hidden>{SERIES[i]!.marker}</span> {p.name}</th>)}</tr></thead>
        <tbody>
          {rowDefs.map((r) => { const best = bestIndexes(r.vals); return (
            <tr key={r.label} className="border-t border-border"><th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium">{r.label}</th>
              {r.vals.map((v, i) => <td key={i} className={cn("p-3 tabular-nums", best.has(i) && "font-bold text-primary")}>{r.fmt(v)}{best.has(i) && <span aria-label="최고점"> 👑</span>}</td>)}</tr>); })}
          <tr className="border-t border-border"><th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium">예상 합불(참고)</th>{P.map((p) => <td key={p.application_id} className="p-3"><Badge>{PRED[p.ai_pass_prediction]}</Badge></td>)}</tr>
          <tr className="border-t border-border"><th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium">시선 이탈률(참고)</th>{P.map((p) => <td key={p.application_id} className="p-3">{pct(p.gaze_away_ratio, 1)}</td>)}</tr>
          <tr className="border-t border-border align-top"><th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium">핵심 강점</th>{P.map((p) => <td key={p.application_id} className="p-3"><ul className="list-disc pl-4">{p.strengths.map((s) => <li key={s}>{s}</li>)}</ul></td>)}</tr>
          <tr className="border-t border-border align-top"><th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium">핵심 개선점</th>{P.map((p) => <td key={p.application_id} className="p-3"><ul className="list-disc pl-4">{p.improvements.map((s) => <li key={s}>{s}</li>)}</ul></td>)}</tr>
          <tr className="border-t border-border"><th scope="row" className="sticky left-0 bg-surface p-3 text-left font-medium">상세</th>{P.map((p) => <td key={p.application_id} className="p-3"><Link className="text-primary" href={`/admin/applications/${p.application_id}`}>상세 보기</Link></td>)}</tr>
        </tbody></table></Card>
      <p className="text-xs text-muted">ⓘ AI 예상 합불과 점수는 참고 지표이며 최종 결정은 담당자가 합니다.</p>
    </div>
  );
}
