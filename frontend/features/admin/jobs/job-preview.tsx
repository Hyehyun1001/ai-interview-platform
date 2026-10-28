"use client";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Badge, Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { JobBody } from "@/features/jobs/job-view";
import { getJob, jobKeys } from "../api";

/** ADM-03p 공고 미리보기: 지원자 시점(APP-03)과 **같은 화면 컴포넌트**로 그린다. 읽기 전용이며 저장·게시 상태와 무관하게 현재 저장된 내용을 보여 준다. */
export function JobPreview({ jobId }: { jobId: string }) {
  const q = useQuery({ queryKey: jobKeys.one(jobId), queryFn: () => getJob(jobId), retry: 1, refetchOnWindowFocus: false });
  if (q.isError) return <Card><ErrorState message="공고를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (!q.data) return <Skeleton className="h-96" />;
  const j = q.data;
  const pool = j.questions.length + j.bank_count;
  return (
    <div className="mx-auto max-w-[1000px]">
      <JobBody
        job={{ title: j.title, company: null, category: j.job_category, deadline: j.deadline_at, headcount: j.headcount, duties: j.duties, requirements: j.requirements, preferred: j.preferred,
          contactEmail: j.contact_email, answerLimitSec: j.answer_time_limit_sec, questionCount: pool > 0 ? Math.min(10, pool) : null, maxFollowups: j.followup_rules.max_followups,
          codingEnabled: j.coding_test_enabled, codingLimitSec: j.coding_test_time_limit_sec,
          workLocation: j.work_location, employmentType: j.employment_type, salaryText: j.salary_text, benefits: j.benefits, notice: j.notice }}
        statusBadge={<Badge tone="neutral">{j.status === "draft" ? "임시 저장" : j.status === "open" ? "게시 중" : "마감"}</Badge>}
        banner={
          <div role="note" className="flex items-center gap-2 rounded bg-info-bg p-3 text-sm text-info" data-testid="preview-banner">
            <span className="font-semibold">미리보기</span><span>지원자에게 보이는 화면입니다. 실제 지원은 할 수 없어요.</span>
            <Link href={`/admin/jobs/${j.id}/edit`} className="ml-auto inline-flex items-center gap-1 font-semibold"><ArrowLeft className="h-4 w-4" aria-hidden />편집으로 돌아가기</Link>
          </div>}
        action={<Button disabled className="w-full">지원하기 / AI 면접 진행</Button>} />
    </div>
  );
}
