"use client";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { JobBody } from "./job-view";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { ddayLabel } from "@/lib/utils";
import { MY_APPS_KEY, applyToJob, fetchMyApplications, useJob, useMyApplications, type JobDetail } from "@/features/applicant/api";
import { ConsentDialog } from "./consent-dialog";
import { CONSENT_VERSION, continueTarget, isDeadlinePassed } from "./logic";

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

  const full = "w-full";
  const cta = myApp
    ? <Button onClick={() => router.push(continueTarget(myApp).href)} className={full}>{continueTarget(myApp).label}</Button>
    : closed
      ? <Button disabled className={full}>모집이 마감되었습니다</Button>
      : <Button onClick={() => { setErr(null); setOpen(true); }} className={full} data-testid="apply-btn">지원하기 / AI 면접 진행</Button>;

  return (
    <div className="space-y-4">
      <Link href="/jobs" className="inline-flex items-center gap-1 text-sm text-muted hover:text-text"><ArrowLeft className="h-4 w-4" aria-hidden />공고 목록</Link>
      <JobBody
        job={{ title: job.title, company: job.company_name, category: job.job_category, deadline: job.deadline_at, headcount: job.headcount, duties: job.duties, requirements: job.requirements,
          preferred: job.preferred, contactEmail: job.contact_email, answerLimitSec: job.answer_time_limit_sec, questionCount: job.interview_question_count, maxFollowups: job.max_followups,
          codingEnabled: job.coding_test_enabled, codingLimitSec: job.coding_test_time_limit_sec,
          workLocation: job.work_location, employmentType: job.employment_type, salaryText: job.salary_text, benefits: job.benefits, notice: job.notice }}
        statusBadge={myApp?.result && <Badge tone={myApp.result === "pass" ? "success" : "neutral"}>{myApp.result === "pass" ? "합격" : "불합격"}</Badge>}
        action={<>{closed && !myApp && dday.tone === "closed" && <p className="mb-2 text-center text-xs text-muted">마감일이 지났습니다</p>}{cta}</>} />
      <ConsentDialog open={open} busy={busy} error={err} onCancel={() => setOpen(false)} onAgree={() => void agree()} />
    </div>
  );
}
