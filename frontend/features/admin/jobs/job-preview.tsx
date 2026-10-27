"use client";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Lock } from "lucide-react";
import Link from "next/link";
import { Badge, Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { DDayBadge } from "@/features/jobs/job-list";
import { formatDeadline } from "@/features/jobs/logic";
import { getJob, jobKeys } from "../api";

function Section({ title, body }: { title: string; body?: string | null }) {
  if (!body?.trim()) return null;
  return <section className="space-y-1"><h2 className="font-bold">■ {title}</h2><p className="whitespace-pre-line text-sm leading-relaxed">{body}</p></section>;
}

/** ADM-03p 공고 미리보기: 지원자 시점(APP-03)으로 보되 읽기 전용이다. 저장·게시 상태와 무관하게 현재 저장된 내용을 보여 준다. */
export function JobPreview({ jobId }: { jobId: string }) {
  const q = useQuery({ queryKey: jobKeys.one(jobId), queryFn: () => getJob(jobId), retry: 1, refetchOnWindowFocus: false });
  if (q.isError) return <Card><ErrorState message="공고를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (!q.data) return <Skeleton className="h-96" />;
  const j = q.data;
  return (
    <div className="mx-auto max-w-[900px] space-y-5">
      <div role="note" className="flex items-center gap-2 rounded bg-info-bg p-3 text-sm text-info" data-testid="preview-banner">
        <span className="font-semibold">미리보기</span><span>지원자에게 보이는 화면입니다. 실제 지원은 할 수 없어요.</span>
        <Link href={`/admin/jobs/${j.id}/edit`} className="ml-auto inline-flex items-center gap-1 font-semibold"><ArrowLeft className="h-4 w-4" aria-hidden />편집으로 돌아가기</Link>
      </div>
      <article className="space-y-5">
        <header className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {j.job_category && <Badge tone="info">{j.job_category}</Badge>}
            <DDayBadge deadline={j.deadline_at} />
            <span className="text-sm text-muted">{formatDeadline(j.deadline_at)}</span>
            <Badge tone="neutral">{j.status === "draft" ? "임시 저장" : j.status === "open" ? "게시 중" : "마감"}</Badge>
          </div>
          <h1 className="text-2xl font-bold">{j.title}</h1>
          <p className="text-sm text-muted">{j.headcount ? `정원 ${j.headcount}명` : ""}{j.coding_test_enabled ? " · 코딩테스트 포함" : ""}{j.answer_time_limit_sec ? ` · 질문당 답변 ${j.answer_time_limit_sec}초` : ""}</p>
        </header>
        <Card className="space-y-5 p-6">
          <Section title="주요 업무" body={j.duties} />
          <Section title="지원 요건" body={j.requirements} />
          <Section title="우대 사항" body={j.preferred} />
        </Card>
        <p className="flex items-center gap-1 text-sm text-muted"><Lock className="h-4 w-4" aria-hidden />AI 면접은 기업 내부망 서버에서만 처리됩니다.</p>
        <div className="flex justify-end"><Button disabled>지원하기 / AI 면접 진행</Button></div>
      </article>
    </div>
  );
}
