"use client";
import { Search } from "lucide-react";
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
      <Card className="h-full space-y-2 p-4 transition hover:border-primary">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {job.job_category && <Badge tone="info">{job.job_category}</Badge>}
            {job.coding_test_enabled && <Badge tone="warning">코딩테스트</Badge>}
          </div>
          <DDayBadge deadline={job.deadline_at} />
        </div>
        <h2 className="text-base font-bold">{job.title}</h2>
        <p className="text-sm text-muted">
          {job.company_name}{job.headcount ? ` · 정원 ${job.headcount}명` : ""}
        </p>
        <p className="text-sm text-muted">{formatDeadline(job.deadline_at)}</p>
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
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">채용 공고</h1>
      <form role="search" className="flex gap-2" onSubmit={(e) => { e.preventDefault(); go({ q: text, page: 1 }); }}>
        <label className="sr-only" htmlFor="job-q">공고 검색</label>
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
          <input id="job-q" value={text} onChange={(e) => setText(e.target.value)} maxLength={100} placeholder="직무·키워드 검색"
            className="h-10 w-full rounded border border-border bg-surface pl-9 pr-3 text-sm" />
        </div>
        <Button type="submit" variant="secondary">검색</Button>
      </form>

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
