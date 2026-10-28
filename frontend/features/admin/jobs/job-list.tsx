"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Code2, Eye, FilePlus2, Search, Users } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { cn, ddayLabel, formatDateTime } from "@/lib/utils";
import { closeJob, deleteJob, jobKeys, listJobs } from "../api";
import { TABS, TAB_LABEL, canConfirmDelete, countByTab, filterJobs, parseTab, type JobItem } from "./job-list-logic";

const STATUS_TONE = { open: "success", closed: "neutral", draft: "warning", deleted: "neutral" } as const;
const STATUS_LABEL = { open: "게시 중", closed: "마감", draft: "임시 저장", deleted: "삭제" } as const;
const linkBtn = "inline-flex h-9 items-center gap-1 rounded border border-border bg-surface px-3 text-xs font-semibold hover:bg-surface-2";

/** ADM-02 공고 목록·현황 (UI_SPEC §5.2): 진행 중/마감/임시저장 탭(URL ?status=), 공고명 검색, 카드별 현황과 액션. */
export function JobList() {
  const sp = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const tab = parseTab(sp.get("status"));
  const [text, setText] = useState("");
  const [closing, setClosing] = useState<JobItem | null>(null);
  const [deleting, setDeleting] = useState<JobItem | null>(null);
  const q = useQuery({ queryKey: jobKeys.list, queryFn: listJobs, retry: 1 });
  const refresh = () => void qc.invalidateQueries({ queryKey: jobKeys.list });

  const items = q.data?.items ?? [];
  const counts = countByTab(items);
  const rows = filterJobs(items, tab, text);
  const setTab = (t: string) => router.replace(`?status=${t}`, { scroll: false });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">공고 관리</h2>
        <Link href="/admin/jobs/new" className="inline-flex h-10 items-center gap-1.5 rounded bg-primary px-4 text-sm font-semibold text-primary-fg" data-testid="new-job"><FilePlus2 className="h-4 w-4" aria-hidden />신규 공고 작성</Link>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="공고 상태" className="flex gap-1 rounded border border-border bg-surface p-1">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} data-testid={`tab-${t}`}
              className={cn("rounded px-3 py-1.5 text-sm", tab === t ? "bg-primary font-semibold text-primary-fg" : "text-muted hover:bg-surface-2")}>{TAB_LABEL[t]} <span className="tabular-nums">({counts[t]})</span></button>
          ))}
        </div>
        <label className="relative ml-auto w-full sm:w-64"><span className="sr-only">공고명 검색</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="공고명 검색" className="h-10 w-full rounded border border-border bg-surface pl-9 pr-3 text-sm" data-testid="job-search" /></label>
      </div>

      {q.isPending && <Skeleton className="h-48" />}
      {q.isError && <Card><ErrorState message="공고를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>}
      {q.data && (rows.length === 0
        ? <Card><EmptyState title={items.length === 0 ? "등록된 공고가 없어요" : text ? "검색 결과가 없어요" : `${TAB_LABEL[tab]} 공고가 없어요`}
            action={items.length === 0 ? <Link href="/admin/jobs/new" className="text-primary">첫 공고 작성하기</Link> : undefined} /></Card>
        : <ul className="space-y-3" aria-label="공고 목록" data-testid="job-cards">
            {rows.map((j) => {
              const d = ddayLabel(j.deadline_at);
              return (
                <li key={j.id}>
                  <Card className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center" data-testid="job-card-admin">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={STATUS_TONE[j.status]}>{STATUS_LABEL[j.status]}</Badge>
                        {j.job_category && <Badge tone="info">{j.job_category}</Badge>}
                        <Badge tone={j.coding_test_enabled ? "warning" : "neutral"} data-testid="coding-flag"><Code2 className="mr-1 inline h-3 w-3" aria-hidden />코딩테스트 {j.coding_test_enabled ? "ON" : "OFF"}</Badge>
                        {j.status === "open" && <Badge tone={d.tone === "today" || d.tone === "soon" ? "danger" : "neutral"}>{d.label}</Badge>}
                      </div>
                      <Link href={`/admin/jobs/${j.id}/edit`} className="block truncate text-base font-bold hover:text-primary hover:underline">{j.title}</Link>
                      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                        <span className="inline-flex items-center gap-1"><Users className="h-3.5 w-3.5" aria-hidden />지원자 <b className="tabular-nums text-text" data-testid="applicant-count">{j.applicant_count}</b>명{j.unreviewed_count > 0 && <Badge tone="warning" className="ml-1">미검토 {j.unreviewed_count}</Badge>}</span>
                        <span className="inline-flex items-center gap-1"><Eye className="h-3.5 w-3.5" aria-hidden />조회 <b className="tabular-nums text-text">{j.view_count}</b></span>
                        <span>마감 {j.deadline_at ? formatDateTime(j.deadline_at) : "미정"}</span>
                        <span>수정 {formatDateTime(j.updated_at)}</span>
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                      {j.applicant_count > 0 && <Link href={`/admin/jobs/${j.id}/applicants`} className={linkBtn}>지원자</Link>}
                      <Link href={`/admin/jobs/${j.id}/preview`} target="_blank" rel="noopener" className={linkBtn}>미리보기</Link>
                      {j.status !== "closed" && <Link href={`/admin/jobs/${j.id}/edit`} className={linkBtn}>수정</Link>}
                      {j.status === "open" && <button type="button" className={linkBtn} onClick={() => setClosing(j)} data-testid="close-job">마감</button>}
                      <button type="button" className={cn(linkBtn, "text-danger")} onClick={() => setDeleting(j)} data-testid="delete-job">삭제</button>
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>)}
      {q.data && q.data.total > items.length && <p className="text-xs text-muted">최근 {items.length}건만 표시했어요. (전체 {q.data.total}건)</p>}

      <CloseDialog job={closing} onClose={() => setClosing(null)} onDone={() => { setClosing(null); refresh(); }} />
      <DeleteDialog job={deleting} onClose={() => setDeleting(null)} onDone={() => { setDeleting(null); refresh(); }} />
    </div>
  );
}

function CloseDialog({ job, onClose, onDone }: { job: JobItem | null; onClose: () => void; onDone: () => void }) {
  const m = useMutation({
    mutationFn: () => closeJob(job!.id),
    onSuccess: () => { toast.success("공고를 마감했어요"); onDone(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "마감하지 못했어요"),
  });
  return (
    <Modal open={!!job} title="공고를 마감할까요?" onClose={() => { if (!m.isPending) onClose(); }}>
      <div className="space-y-3 text-sm">
        <p><b>{job?.title}</b> 공고의 접수를 마감합니다. 마감한 공고는 다시 열 수 없어요.</p>
        <p className="text-muted">이미 진행 중인 면접은 계속 진행됩니다.</p>
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose} disabled={m.isPending}>취소</Button><Button variant="danger" loading={m.isPending} onClick={() => m.mutate()} data-testid="close-confirm">마감하기</Button></div>
      </div>
    </Modal>
  );
}

function DeleteDialog({ job, onClose, onDone }: { job: JobItem | null; onClose: () => void; onDone: () => void }) {
  const [typed, setTyped] = useState("");
  const m = useMutation({
    mutationFn: () => deleteJob(job!.id),
    onSuccess: () => { toast.success("공고를 삭제했어요"); setTyped(""); onDone(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "삭제하지 못했어요"),
  });
  const hasApplicants = (job?.applicant_count ?? 0) > 0;
  return (
    <Modal open={!!job} title="공고를 삭제할까요?" onClose={() => { if (!m.isPending) { setTyped(""); onClose(); } }}>
      <div className="space-y-3 text-sm">
        {hasApplicants
          ? <p role="alert" className="rounded bg-danger-bg p-3 text-danger">이 공고에는 지원자가 <b>{job?.applicant_count}명</b> 있어요. 삭제하면 공고가 목록과 지원자 화면에서 사라집니다. (지원 기록은 보존됩니다)</p>
          : <p>삭제하면 공고가 목록에서 사라집니다.</p>}
        <label className="block">확인을 위해 공고명을 입력하세요<span className="mt-1 block rounded bg-surface-2 px-2 py-1 text-xs">{job?.title}</span>
          <input className="mt-2 h-10 w-full rounded border border-border bg-surface px-3" value={typed} onChange={(e) => setTyped(e.target.value)} data-testid="delete-confirm-input" autoComplete="off" /></label>
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => { setTyped(""); onClose(); }} disabled={m.isPending}>취소</Button>
          <Button variant="danger" disabled={!job || !canConfirmDelete(job.title, typed)} loading={m.isPending} onClick={() => m.mutate()} data-testid="delete-confirm">삭제</Button></div>
      </div>
    </Modal>
  );
}
