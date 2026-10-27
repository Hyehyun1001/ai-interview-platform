"use client";
import { useQuery } from "@tanstack/react-query";
import { Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { components } from "@/types/api";

type Resume = components["schemas"]["ResumeSnapshotOut"];
const show = (v?: string | null) => (v && v.trim() ? v : "-");

/** ADM-06 표준 이력서 탭: 지원 시점에 확정된 스냅샷의 통합 표준 양식(읽기 전용). 마이페이지에서 나중에 고친 내용은 반영되지 않는다. */
export function ResumeTab({ applicationId }: { applicationId: string }) {
  const q = useQuery({ queryKey: ["admin", "resume", applicationId], queryFn: () => apiFetch<Resume>(`/api/v1/applications/${applicationId}/resume/standard`), retry: false, refetchOnWindowFocus: false });
  if (q.isError) {
    const gone = q.error instanceof ApiError && q.error.status === 404;
    return <Card><ErrorState message={gone ? "이력서를 찾을 수 없어요" : "이력서를 불러오지 못했어요"} onRetry={gone ? undefined : () => void q.refetch()} /></Card>;
  }
  if (!q.data) return <Skeleton className="h-64" />;
  const d = q.data.data;
  const empty = !d.name && !d.education?.length && !d.experience?.length && !d.projects?.length && !d.skills?.length;
  if (empty) return <Card><EmptyState title="표준 이력서 정보가 비어 있어요" /></Card>;
  return (
    <Card className="space-y-5 p-5" data-testid="resume-tab">
      <header className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-lg font-bold">{show(d.name)}</h2><p className="text-xs text-muted">지원 시점에 확정된 표준 이력서 · 읽기 전용</p></header>
      <Section title="학력" empty={!d.education?.length}>{d.education?.map((e, i) => (
        <li key={i}><b>{show(e.school)}</b> {e.major && `· ${e.major}`} {e.degree && `(${e.degree})`}<span className="ml-2 text-xs text-muted">{[e.start, e.end].filter(Boolean).join(" ~ ")}</span></li>))}</Section>
      <Section title="경력" empty={!d.experience?.length}>{d.experience?.map((e, i) => (
        <li key={i}><b>{show(e.company)}</b> {e.role && `· ${e.role}`}<span className="ml-2 text-xs text-muted">{[e.start, e.end].filter(Boolean).join(" ~ ")}</span>{e.summary && <p className="whitespace-pre-line text-muted">{e.summary}</p>}</li>))}</Section>
      <Section title="프로젝트" empty={!d.projects?.length}>{d.projects?.map((p, i) => (
        <li key={i}><b>{show(p.title)}</b> {p.role && `· ${p.role}`}<span className="ml-2 text-xs text-muted">{p.period}</span>
          {!!p.tech_stack?.length && <p className="text-xs text-muted">{p.tech_stack.join(", ")}</p>}{p.description && <p className="whitespace-pre-line text-muted">{p.description}</p>}</li>))}</Section>
      <section><h3 className="mb-1 font-semibold">기술</h3>{d.skills?.length ? <ul className="flex flex-wrap gap-1" aria-label="기술 목록">{d.skills.map((s) => <li key={s} className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">{s}</li>)}</ul> : <p className="text-sm text-muted">-</p>}</section>
      {!!d.certifications?.length && <section><h3 className="mb-1 font-semibold">자격증</h3><p className="text-sm">{d.certifications.join(", ")}</p></section>}
      {d.self_intro && <section><h3 className="mb-1 font-semibold">자기소개</h3><p className="whitespace-pre-line text-sm leading-relaxed">{d.self_intro}</p></section>}
    </Card>
  );
}

function Section({ title, empty, children }: { title: string; empty: boolean; children: React.ReactNode }) {
  return <section><h3 className="mb-1 font-semibold">{title}</h3>{empty ? <p className="text-sm text-muted">-</p> : <ul className="space-y-2 text-sm">{children}</ul>}</section>;
}
