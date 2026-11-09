"use client";
import { FileText, Mic, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { LevelMeter } from "@/components/ui/level-meter";
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
      <Card className="h-full space-y-3 p-5 transition-colors duration-150 hover:border-accent">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {job.job_category && <Badge tone="info">{job.job_category}</Badge>}
            {job.coding_test_enabled && <Badge tone="warning">코딩테스트</Badge>}
          </div>
          <DDayBadge deadline={job.deadline_at} />
        </div>
        <div className="flex items-center gap-3">
          <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-navy text-sm font-semibold text-accent">{job.company_name.slice(0, 1)}</span>
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{job.title}</h2>
            <p className="truncate text-sm text-muted">{job.company_name}{job.headcount ? ` · ${job.headcount}명 채용` : ""}</p>
          </div>
        </div>
        <p className="border-t border-border pt-3 text-xs text-muted">{formatDeadline(job.deadline_at)}</p>
        {applied && <Badge tone="success">지원 완료</Badge>}
      </Card>
    </Link>
  );
}

/** 랜딩 히어로의 샘플 리포트. 화면용 예시 데이터이며 실제 지원자 결과가 아니다. */
function ReportPreview() {
  const rows = [
    { label: "직무 이해도", score: 4, on: true },
    { label: "문제 해결", score: 3, on: false },
    { label: "의사소통", score: 4, on: false },
  ];
  return (
    <figure aria-label="결과 리포트 예시" className="rounded-xl bg-surface p-5 text-text">
      <figcaption className="flex items-center justify-between text-xs text-muted"><span>결과 리포트 예시</span><span>샘플</span></figcaption>
      <ul className="mt-4 space-y-2">
        {rows.map((r) => (
          <li key={r.label} className={cn("flex items-center gap-3 rounded-lg px-3 py-2 text-sm", r.on ? "bg-surface-2" : "")}>
            <span className="flex-1">{r.label}</span>
            <span className="flex gap-1" aria-hidden>{Array.from({ length: 5 }, (_, i) => <span key={i} className={cn("h-1.5 w-4 rounded-sm", i < r.score ? "bg-primary" : "bg-border")} />)}</span>
            <span className="w-8 text-right tabular-nums text-muted">{r.score}.0</span>
          </li>
        ))}
      </ul>
      <blockquote className="mt-4 border-l-2 border-accent pl-3 text-sm leading-relaxed">
        <p>“캐시 무효화 시점을 이벤트 기준으로 바꿔서 응답 시간을 줄였습니다.”</p>
        <p className="mt-2 text-xs text-muted">직무 이해도 근거 · 질문 2 답변 00:41</p>
      </blockquote>
    </figure>
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
      <section className="overflow-hidden rounded-2xl bg-brand-navy px-6 py-10 text-white sm:px-10 sm:py-12">
        <div className="grid items-center gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)]">
          <div>
            <p className="mb-4 inline-flex items-center gap-2 text-sm text-slate-300"><LevelMeter className="text-accent" />AI 음성 면접</p>
            <h1 className="text-3xl font-semibold leading-snug sm:text-4xl">음성으로 답하고,<br />근거가 담긴 결과를 받는 면접</h1>
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-slate-300 sm:text-base">내 이력서에서 출발한 질문에 말로 답하면, 점수마다 답변 속 근거 문장이 함께 표시됩니다.</p>
            <form role="search" className="mt-8 flex gap-2" onSubmit={(e) => { e.preventDefault(); go({ q: text, page: 1 }); }}>
              <label className="sr-only" htmlFor="job-q">공고 검색</label>
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" strokeWidth={1.5} aria-hidden />
                <input id="job-q" value={text} onChange={(e) => setText(e.target.value)} maxLength={100} placeholder="직무나 키워드"
                  className="h-12 w-full rounded-lg border border-transparent bg-white pl-11 pr-3 text-sm text-text placeholder:text-muted" />
              </div>
              <button type="submit" className="h-12 rounded-lg bg-accent px-6 text-sm font-semibold text-brand-navy transition-colors duration-150 hover:bg-white">검색</button>
            </form>
          </div>
          <ReportPreview />
        </div>
      </section>

      <ul className="grid gap-4 sm:grid-cols-3" aria-label="서비스 특징">
        {[
          { Icon: Mic, title: "음성으로 답변", desc: "타이핑 없이 말로, 내 속도에 맞춰 진행됩니다" },
          { Icon: FileText, title: "이력서 기반 질문", desc: "경험에서 출발해 꼬리질문까지 이어집니다" },
          { Icon: ShieldCheck, title: "기업 서버 안에서 보관", desc: "음성과 이력서는 외부로 전송되지 않습니다" },
        ].map(({ Icon, title, desc }) => (
          <li key={title} className="flex items-start gap-3 rounded-lg border border-border bg-surface p-4">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted" strokeWidth={1.5} aria-hidden />
            <div><p className="text-sm font-medium">{title}</p><p className="mt-1 text-xs leading-relaxed text-muted">{desc}</p></div>
          </li>
        ))}
      </ul>

      <h2 className="pt-2 text-xl font-semibold">지금 모집 중인 공고</h2>

      <div role="group" aria-label="직무 카테고리" className="flex flex-wrap gap-2">
        {[null, ...CATEGORIES].map((c) => {
          const on = (query.category ?? null) === c;
          return (
            <button key={c ?? "all"} type="button" aria-pressed={on} onClick={() => go({ category: c, page: 1 })}
              className={cn("h-9 rounded-full border px-4 text-sm font-medium transition-colors duration-150", on ? "border-primary bg-primary text-primary-fg" : "border-border bg-surface hover:bg-surface-2")}>
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
          <p className="text-sm text-muted" data-testid="job-total"><span className="tabular-nums">총 {jobs.data.total}건</span> · 마감임박순</p>
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
          className={cn("h-9 min-w-9 rounded px-2 text-sm", p === page ? "bg-primary font-semibold text-primary-fg" : "hover:bg-surface-2")}>{p}</button>
      ))}
      <Button variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="다음 페이지">›</Button>
    </nav>
  );
}
