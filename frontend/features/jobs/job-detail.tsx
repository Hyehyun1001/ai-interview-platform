"use client";
import { ArrowLeft, Lock } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { ddayLabel } from "@/lib/utils";
import { MY_APPS_KEY, applyToJob, fetchMyApplications, useJob, useMyApplications, type JobDetail } from "@/features/applicant/api";
import { ConsentDialog } from "./consent-dialog";
import { DDayBadge } from "./job-list";
import { CONSENT_VERSION, continueTarget, formatDeadline, isDeadlinePassed } from "./logic";

function Section({ title, body }: { title: string; body?: string | null }) {
  if (!body?.trim()) return null;
  // 담당자가 입력한 텍스트이므로 HTML 로 해석하지 않고 줄바꿈만 보존한다 (XSS 방지)
  return <section className="space-y-1"><h2 className="font-bold">■ {title}</h2><p className="whitespace-pre-line text-sm leading-relaxed">{body}</p></section>;
}

/** APP-03 공고 상세 + 지원 CTA + 동의 모달 (UI_SPEC §4.2.2). */
export function JobDetailView({ jobId }: { jobId: string }) {
  const q = useJob(jobId);
  if (q.isError) {
    const notFound = q.error instanceof ApiError && (q.error.status === 404 || q.error.status === 422);
    return <Card className="mx-auto max-w-lg"><ErrorState message={notFound ? "공고를 찾을 수 없습니다" : "공고를 불러오지 못했어요"} onRetry={notFound ? undefined : () => void q.refetch()} />
      <div className="pb-6 text-center"><Link href="/jobs" className="text-primary">공고 목록으로</Link></div></Card>;
  }
  if (!q.data) return <div className="space-y-3" aria-busy><Skeleton className="h-8 w-64" /><Skeleton className="h-48 w-full" /></div>;
  return <Loaded job={q.data} />;
}

function Loaded({ job }: { job: JobDetail }) {
  const router = useRouter();
  const qc = useQueryClient();
  const mine = useMyApplications();
  const myApp = (mine.data ?? []).find((a) => a.job.id === job.id);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [closedByServer, setClosedByServer] = useState(false);
  const closed = closedByServer || isDeadlinePassed(job.deadline_at);
  const dday = ddayLabel(job.deadline_at);

  async function agree() {
    setBusy(true);
    setErr(null);
    try {
      const r = await applyToJob(job.id, CONSENT_VERSION);
      void qc.invalidateQueries({ queryKey: MY_APPS_KEY });
      router.push(`/apply/${r.application_id}/resume`);
    } catch (e) {
      if (e instanceof ApiError && e.code === "ALREADY_APPLIED") {  // 이미 지원: 기존 지원 건으로 이어서 진행
        toast.info("이미 지원한 공고입니다. 이어서 진행합니다.");
        const apps = await qc.fetchQuery({ queryKey: MY_APPS_KEY, queryFn: fetchMyApplications, staleTime: 0 }).catch(() => []);
        const id = String(e.details["application_id"] ?? "");
        const app = apps.find((a) => a.application_id === id);
        router.push(app ? continueTarget(app).href : `/apply/${id}/resume`);
        return;
      }
      if (e instanceof ApiError && e.code === "JOB_CLOSED") {
        toast.error("이미 마감된 공고입니다", { code: e.code });
        setClosedByServer(true);
        setOpen(false);
      } else {
        setErr(e instanceof ApiError ? e.message : "동의 처리에 실패했어요. 다시 시도해 주세요.");
      }
    } finally { setBusy(false); }
  }

  const cta = myApp
    ? <Button onClick={() => router.push(continueTarget(myApp).href)} className="w-full sm:w-auto">{continueTarget(myApp).label}</Button>
    : closed
      ? <Button disabled className="w-full sm:w-auto">모집이 마감되었습니다</Button>
      : <Button onClick={() => { setErr(null); setOpen(true); }} className="w-full sm:w-auto" data-testid="apply-btn">지원하기 / AI 면접 진행</Button>;

  return (
    <article className="space-y-6">
      <Link href="/jobs" className="inline-flex items-center gap-1 text-sm text-muted hover:text-text"><ArrowLeft className="h-4 w-4" aria-hidden />공고 목록</Link>
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          {job.job_category && <Badge tone="info">{job.job_category}</Badge>}
          <DDayBadge deadline={job.deadline_at} />
          <span className="text-sm text-muted">{formatDeadline(job.deadline_at)}</span>
          {myApp?.result && <Badge tone={myApp.result === "pass" ? "success" : "neutral"}>{myApp.result === "pass" ? "합격" : "불합격"}</Badge>}
        </div>
        <h1 className="text-2xl font-bold">{job.title}</h1>
        <p className="text-sm text-muted">
          {job.company_name}{job.headcount ? ` · 정원 ${job.headcount}명` : ""}
          {job.coding_test_enabled ? " · 코딩테스트 포함" : ""}{job.answer_time_limit_sec ? ` · 질문당 답변 ${job.answer_time_limit_sec}초` : ""}
        </p>
      </header>
      <Card className="space-y-5 p-6">
        <Section title="주요 업무" body={job.duties} />
        <Section title="지원 요건" body={job.requirements} />
        <Section title="우대 사항" body={job.preferred} />
      </Card>
      <p className="flex items-center gap-1 text-sm text-muted"><Lock className="h-4 w-4" aria-hidden />AI 면접은 기업 내부망 서버에서만 처리됩니다.</p>
      <div className="sticky bottom-0 -mx-4 flex items-center justify-end gap-3 border-t border-border bg-surface px-4 py-3 sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:px-0">
        {closed && !myApp && dday.tone === "closed" && <span className="text-sm text-muted">마감일이 지났습니다</span>}
        {cta}
      </div>
      <ConsentDialog open={open} busy={busy} error={err} onCancel={() => setOpen(false)} onAgree={() => void agree()} />
    </article>
  );
}
