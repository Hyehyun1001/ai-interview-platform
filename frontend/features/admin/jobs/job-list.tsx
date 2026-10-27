"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ddayLabel } from "@/lib/utils";
import { jobKeys, listJobs } from "../api";

const STATUS = { draft: "임시 저장", open: "게시 중", closed: "마감", deleted: "삭제" } as const;

export function JobList() {
  const q = useQuery({ queryKey: jobKeys.list, queryFn: listJobs, retry: 1 });
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h1 className="text-xl font-bold">공고 관리</h1>
        <Link href="/admin/jobs/new" className="inline-flex h-10 items-center rounded bg-primary px-4 text-sm font-semibold text-primary-fg">＋ 신규 공고 작성</Link></div>
      {q.isPending && <Skeleton className="h-48" />}
      {q.isError && <Card><ErrorState message="공고를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>}
      {q.data && (q.data.items.length === 0 ? <Card><EmptyState title="등록된 공고가 없어요" /></Card> : (
        <Card className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm"><thead className="text-left text-muted"><tr><th className="p-3">공고명</th><th>상태</th><th>마감</th><th>지원자</th><th>미검토</th></tr></thead>
          <tbody>{q.data.items.map((j) => (<tr key={j.id} className="border-t border-border"><td className="p-3"><Link className="font-medium text-primary" href={`/admin/jobs/${j.id}/edit`}>{j.title}</Link></td>
            <td><Badge tone={j.status === "open" ? "success" : "neutral"}>{STATUS[j.status]}</Badge></td><td>{ddayLabel(j.deadline_at).label}</td><td>{j.applicant_count > 0 ? <Link className="text-primary hover:underline" href={`/admin/jobs/${j.id}/applicants`}>{j.applicant_count}명 보기</Link> : 0}</td><td>{j.unreviewed_count}</td></tr>))}</tbody></table></Card>))}
    </div>
  );
}
