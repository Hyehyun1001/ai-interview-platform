"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { formatDateTime } from "@/lib/utils";
import { addNote, listNotes, noteKeys } from "../api";

const MAX = 2000;

/** ADM-06 메모 탭: 내부 메모 타임라인 + 작성. 지원자에게는 노출되지 않는다 (UI_SPEC §5.6.4). */
export function NotesTab({ applicationId }: { applicationId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: noteKeys.list(applicationId), queryFn: () => listNotes(applicationId), retry: 1 });
  const [text, setText] = useState("");
  const m = useMutation({
    mutationFn: () => addNote(applicationId, text.trim()),
    onSuccess: () => { setText(""); toast.success("메모를 남겼어요"); void qc.invalidateQueries({ queryKey: noteKeys.list(applicationId) }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "메모를 저장하지 못했어요"),
  });
  return (
    <div className="space-y-4" data-testid="notes-tab">
      <Card className="space-y-2 p-4">
        <label htmlFor="note-body" className="text-sm font-medium">내부 메모 <span className="text-xs font-normal text-muted">(지원자에게 보이지 않음)</span></label>
        <textarea id="note-body" className="h-24 w-full rounded border border-border bg-surface p-2 text-sm" value={text} maxLength={MAX} onChange={(e) => setText(e.target.value)} />
        <div className="flex items-center justify-between"><span className="text-xs text-muted tabular-nums">{text.length}/{MAX}</span>
          <Button onClick={() => m.mutate()} disabled={!text.trim()} loading={m.isPending} data-testid="note-submit">메모 남기기</Button></div>
      </Card>
      {q.isError ? <Card><ErrorState message="메모를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>
        : !q.data ? <Skeleton className="h-24" />
        : q.data.length === 0 ? <Card><EmptyState title="아직 메모가 없어요" /></Card>
        : <ol className="space-y-2" aria-label="메모 타임라인">{q.data.map((n) => (
          <li key={n.id}><Card className="p-3"><p className="whitespace-pre-line text-sm">{n.body}</p>
            <p className="mt-1 text-xs text-muted">{n.author_name ?? "삭제된 계정"}{n.mine && " (나)"} · {formatDateTime(n.created_at)}</p></Card></li>))}</ol>}
    </div>
  );
}
