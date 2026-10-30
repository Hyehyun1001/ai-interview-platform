"use client";
import { Mic, Search, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { cn, ddayLabel, type DDayTone } from "@/lib/utils";
import { useJobs, useMyApplications, type JobSummary } from "@/features/applicant/api";
import { CATEGORIES, PAGE_SIZE, buildJobsHref, formatDeadline, parseJobsQuery, totalPages } from "./logic";

const DDAY_TONE: Record<DDayTone, "neutral" | "warning" | "danger"> = { normal: "neutral", soon: "warning", today: "danger", closed: "neutral", none: "neutral" };

export function DDayBadge({ deadline }: { deadline: string | null | undefined }) {
  const d = ddayLabel(deadline);
  return <Badge tone={DDAY_TONE[d.tone]} data-testid="dday">{d.label}</Badge>;
}

function JobCard({ job, applied }: { job: JobSummary; applied: boolean }) {
  return (
    <Link href={`/jobs/${job.id}`} data-testid="job-card" className="block rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
      <Card className="h-full space-y-3 p-5 transition duration-200 hover:-translate-y-0.5 hover:border-accent hover:shadow-md">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {job.job_category && <Badge tone="info">{job.job_category}</Badge>}
            {job.coding_test_enabled && <Badge tone="warning">코딩테스트</Badge>}
          </div>
          <DDayBadge deadline={job.deadline_at} />
        </div>
        <div className="flex items-center gap-3">
          <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-navy text-sm font-bold text-accent">{job.company_name.slice(0, 1)}</span>
          <div className="min-w-0">
            <h2 className="truncate text-base font-bold">{job.title}</h2>
            <p className="truncate text-sm text-muted">{job.company_name}{job.headcount ? ` · ${job.headcount}명 채용` : ""}</p>
          </div>
        </div>
        <p className="border-t border-border pt-3 text-xs text-muted">{formatDeadline(job.deadline_at)}</p>
        {applied && <Badge tone="success">지원 완료 ✓</Badge>}
      </Card>
    </Link>
  );
}

/** APP-02 공고 목록. 필터·검색·페이지는 URL 쿼리가 단일 진실 원천이다 (UI_SPEC §4.2.1). */
export function JobList() {
  const router = useRouter();
  const sp = useSearchParams();
  const query = parseJobsQuery(sp);
  const [text, setText] = useState(query.q);
  useEffect(() => setText(query.q), [query.q]);

  const jobs = useJobs({ ...query, limit: PAGE_SIZE });
  const mine = useMyApplications();
  const appliedIds = new Set((mine.data ?? []).map((a) => a.job.id));
  const go = (p: { category?: string | null; q?: string; page?: number }) => router.replace(buildJobsHref({ category: query.category, q: query.q, ...p }), { scroll: false });
  const hasFilter = !!query.category || !!query.q;

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-2xl bg-brand-navy px-6 py-10 text-white sm:px-10 sm:py-14">
        <div aria-hidden className="pointer-events-none absolute -right-20 -top-24 h-80 w-80 rounded-full" style={{ background: "radial-gradient(closest-side, rgba(20,184,166,0.35), transparent)" }} />
        <div aria-hidden className="pointer-events-none absolute -bottom-28 right-32 h-72 w-72 rounded-full" style={{ background: "radial-gradient(closest-side, rgba(56,189,248,0.25), transparent)" }} />
        <div className="relative max-w-2xl">
          <p className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold text-accent"><Sparkles className="h-3.5 w-3.5" aria-hidden />AI 음성 면접</p>
          <h1 className="text-3xl font-extrabold leading-tight tracking-tight sm:text-4xl">말하는 만큼, 정확하게 평가받는<br />새로운 면접</h1>
          <p className="mt-3 text-sm leading-relaxed text-slate-300 sm:text-base">면접관 앞에서 긴장하지 않아도 괜찮아요. 내 이력서에서 출발한 질문에 편하게 답하면, 근거가 담긴 결과로 돌아옵니다.</p>
          <form role="search" className="mt-7 flex gap-2" onSubmit={(e) => { e.preventDefault(); go({ q: text, page: 1 }); }}>
            <label className="sr-only" htmlFor="job-q">공고 검색</label>
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
              <input id="job-q" value={text} onChange={(e) => setText(e.target.value)} maxLength={100} placeholder="직무나 키워드로 공고를 찾아보세요"
                className="h-12 w-full rounded-lg border border-transparent bg-white pl-11 pr-3 text-sm text-text shadow-lg placeholder:text-muted" />
            </div>
            <button type="submit" className="h-12 rounded-lg bg-accent px-6 text-sm font-bold text-brand-navy shadow-lg transition hover:brightness-110">검색</button>
          </form>
        </div>
      </section>

      <ul className="grid gap-3 sm:grid-cols-3" aria-label="서비스 특징">
        {[
          { Icon: Mic, title: "말로 편하게 답변", desc: "타이핑 없이 음성으로, 내 속도에 맞춰 진행돼요." },
          { Icon: Sparkles, title: "이력서 기반 맞춤 질문", desc: "경험에서 출발해 꼬리질문까지 자연스럽게 이어져요." },
          { Icon: ShieldCheck, title: "안심하고 맡기는 내 데이터", desc: "음성과 이력서는 기업 서버 안에서만 보관돼요." },
        ].map(({ Icon, title, desc }) => (
          <li key={title} className="flex items-start gap-3 rounded-lg border border-border bg-surface p-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-primary" style={{ backgroundColor: "color-mix(in srgb, var(--color-accent) 15%, white)" }}><Icon className="h-5 w-5" aria-hidden /></span>
            <div><p className="text-sm font-bold">{title}</p><p className="mt-0.5 text-xs leading-relaxed text-muted">{desc}</p></div>
          </li>
        ))}
      </ul>

      <h2 className="pt-2 text-xl font-bold">지금 모집 중인 공고</h2>

      <div role="group" aria-label="직무 카테고리" className="flex flex-wrap gap-2">
        {[null, ...CATEGORIES].map((c) => {
          const on = (query.category ?? null) === c;
          return (
            <button key={c ?? "all"} type="button" aria-pressed={on} onClick={() => go({ category: c, page: 1 })}
              className={cn("h-9 rounded-full border px-4 text-sm font-medium", on ? "border-primary bg-primary text-primary-fg" : "border-border bg-surface hover:bg-surface-2")}>
              {c ?? "전체"}
            </button>
          );
        })}
      </div>

      {jobs.isError ? (
        <Card><ErrorState message="공고를 불러오지 못했어요" onRetry={() => void jobs.refetch()} /></Card>
      ) : !jobs.data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy>{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : jobs.data.items.length === 0 ? (
        <Card><EmptyState title="조건에 맞는 공고가 없습니다" action={hasFilter ? <Button variant="secondary" onClick={() => { setText(""); router.replace("/jobs", { scroll: false }); }}>필터 초기화</Button> : undefined} /></Card>
      ) : (
        <>
          <p className="text-sm text-muted" data-testid="job-total">총 {jobs.data.total}건 · 마감임박순</p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {jobs.data.items.map((j) => <JobCard key={j.id} job={j} applied={j.applicant_applied || appliedIds.has(j.id)} />)}
          </div>
          <Pagination page={jobs.data.page} pages={totalPages(jobs.data.total, jobs.data.limit)} onPage={(p) => go({ page: p })} />
        </>
      )}
    </div>
  );
}

function Pagination({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  if (pages <= 1) return null;
  return (
    <nav aria-label="페이지" className="flex items-center justify-center gap-1">
      <Button variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="이전 페이지">‹</Button>
      {Array.from({ length: pages }, (_, i) => i + 1).map((p) => (
        <button key={p} type="button" aria-current={p === page ? "page" : undefined} onClick={() => onPage(p)}
          className={cn("h-9 min-w-9 rounded px-2 text-sm", p === page ? "bg-primary font-bold text-primary-fg" : "hover:bg-surface-2")}>{p}</button>
      ))}
      <Button variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="다음 페이지">›</Button>
    </nav>
  );
}
