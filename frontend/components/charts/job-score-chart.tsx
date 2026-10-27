"use client";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { JobCategoryStat } from "@/types/admin";

const RADAR_MIN_AXES = 3;  // 축이 3개 미만이면 레이더가 선/점으로 퇴화한다

/** 직무별 평균 점수 / 합격률. 레이더·막대 토글, 레이더는 직무 3개 이상일 때만 (UI_SPEC §ADM-01 Upper). */
export function JobScoreChart({ stats }: { stats: JobCategoryStat[] }) {
  const radarOk = stats.length >= RADAR_MIN_AXES;
  const [mode, setMode] = useState<"radar" | "bar">(radarOk ? "radar" : "bar");
  const view = radarOk ? mode : "bar";
  const data = stats.map((s) => ({ name: s.category, 평균점수: s.avg_score, 합격률: s.pass_rate == null ? null : Math.round(s.pass_rate * 100) }));
  return (
    <div>
      <div className="mb-2 flex justify-end gap-1" role="group" aria-label="차트 종류">
        {(["radar", "bar"] as const).map((m) => (
          <button key={m} type="button" disabled={m === "radar" && !radarOk} aria-pressed={view === m} onClick={() => setMode(m)}
            title={m === "radar" && !radarOk ? "직무가 3개 이상일 때 사용할 수 있어요" : undefined}
            className="rounded border border-border px-2 py-1 text-xs aria-pressed:bg-primary aria-pressed:text-primary-fg disabled:opacity-40">
            {m === "radar" ? "레이더" : "막대"}
          </button>
        ))}
      </div>
      <div className="h-64" role="img" aria-label={`직무별 평균 점수와 합격률: ${stats.map((s) => `${s.category} ${s.avg_score}점`).join(", ")}`}>
        <ResponsiveContainer width="100%" height="100%">
          {view === "radar" ? (
            <RadarChart data={data}>
              <PolarGrid /><PolarAngleAxis dataKey="name" /><PolarRadiusAxis domain={[0, 100]} />
              <Radar dataKey="평균점수" stroke="var(--chart-1, #2563eb)" fill="var(--chart-1, #2563eb)" fillOpacity={0.3} />
              <Tooltip />
            </RadarChart>
          ) : (
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" /><YAxis domain={[0, 100]} /><Tooltip />
              <Bar dataKey="평균점수" fill="var(--chart-1, #2563eb)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="합격률" fill="var(--chart-2, #16a34a)" radius={[4, 4, 0, 0]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {/* 차트는 시각 전용이므로 같은 수치를 표로도 제공한다 (접근성) */}
      <table className="sr-only"><caption>직무별 평균 점수·합격률</caption><thead><tr><th>직무</th><th>평균 점수</th><th>합격률(%)</th></tr></thead>
        <tbody>{data.map((d) => <tr key={d.name}><td>{d.name}</td><td>{d.평균점수}</td><td>{d.합격률 ?? "—"}</td></tr>)}</tbody></table>
    </div>
  );
}

export function MonthlyApplicantsChart({ data }: { data: { month: string; count: number }[] }) {
  return (
    <div className="h-48" role="img" aria-label={`월별 지원자 수: ${data.map((d) => `${d.month} ${d.count}명`).join(", ")}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="month" /><YAxis allowDecimals={false} /><Tooltip />
          <Bar dataKey="count" name="지원자" fill="var(--chart-1, #2563eb)" radius={[4, 4, 0, 0]} /></BarChart>
      </ResponsiveContainer>
    </div>
  );
}
