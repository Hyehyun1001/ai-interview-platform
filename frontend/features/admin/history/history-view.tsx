"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { cn, formatDateTime } from "@/lib/utils";
import { adminKeys, fetchJobHistory, markNotificationRead, useNotifications } from "../api";
import { ACTION_LABEL, NOTI_LABEL, notificationHref } from "./history-logic";

const TABS = [{ id: "notifications", label: "알림" }, { id: "jobs", label: "공고 이력" }] as const;
type Tab = (typeof TABS)[number]["id"];

/** ADM-08 이력·알림 센터: 알림(읽음 처리·클릭 시 해당 화면 이동) / 공고 이력(작성·게시·마감). */
export function HistoryView() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab: Tab = sp.get("tab") === "jobs" ? "jobs" : "notifications";
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="이력·알림" className="flex gap-1 border-b border-border">
        {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => router.replace(`?tab=${t.id}`, { scroll: false })}
          className={cn("px-4 py-2 text-sm", tab === t.id ? "border-b-2 border-primary font-semibold" : "text-muted")}>{t.label}</button>)}
      </div>
      {tab === "notifications" ? <Notifications /> : <JobHistory />}
    </div>
  );
}

function Notifications() {
  const router = useRouter();
  const qc = useQueryClient();
  const q = useNotifications();
  const read = useMutation({ mutationFn: markNotificationRead, onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.notifications }) });
  if (q.isError) return <Card><ErrorState message="알림을 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (!q.data) return <Skeleton className="h-48" />;
  if (q.data.items.length === 0) return <Card><EmptyState title="새 알림이 없어요" /></Card>;
  const unread = q.data.items.filter((n) => !n.read_at);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm"><span className="text-muted">읽지 않은 알림 {q.data.unread_count}건</span>
        <Button variant="secondary" disabled={unread.length === 0 || read.isPending} onClick={() => unread.forEach((n) => read.mutate(n.id))} data-testid="read-all">모두 읽음</Button></div>
      <ul className="space-y-2" aria-label="알림 목록" data-testid="notification-list">
        {q.data.items.map((n) => {
          const href = notificationHref(n.type, n.payload);
          return (
            <li key={n.id}>
              <button type="button" disabled={!href && !!n.read_at} onClick={() => { if (!n.read_at) read.mutate(n.id); if (href) router.push(href); }}
                className={cn("flex w-full items-center gap-3 rounded border p-3 text-left hover:bg-surface-2", n.read_at ? "border-border text-muted" : "border-primary/40 bg-primary/5")} data-testid="notification-item">
                {!n.read_at && <span className="h-2 w-2 shrink-0 rounded-full bg-primary" aria-label="읽지 않음" />}
                <span className="flex-1">{NOTI_LABEL[n.type] ?? n.type}</span>
                <span className="text-xs tabular-nums text-muted">{formatDateTime(n.created_at)}</span>
              </button>
            </li>);
        })}
      </ul>
      <p className="text-xs text-muted">최근 50건까지 표시합니다. 알림에는 지원자 이름·점수가 담기지 않습니다.</p>
    </div>
  );
}

function JobHistory() {
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["admin", "job-history", page], queryFn: () => fetchJobHistory(page), retry: 1, placeholderData: (p) => p });
  if (q.isError) return <Card><ErrorState message="공고 이력을 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (!q.data) return <Skeleton className="h-48" />;
  if (q.data.total === 0) return <Card><EmptyState title="공고 이력이 없어요" /></Card>;
  const pages = Math.max(1, Math.ceil(q.data.total / q.data.limit));
  return (
    <div className="space-y-3">
      <Card className="overflow-x-auto p-0">
        <table className="w-full min-w-[560px] text-sm" data-testid="history-table">
          <thead className="text-left text-muted"><tr><th className="p-3">일시</th><th>공고</th><th>동작</th><th>담당자</th></tr></thead>
          <tbody>{q.data.items.map((h) => (
            <tr key={h.id} className="border-t border-border"><td className="p-3 tabular-nums text-muted">{formatDateTime(h.created_at)}</td><td className="font-medium">{h.job_title}</td>
              <td><Badge tone={h.action === "published" ? "success" : "neutral"}>{ACTION_LABEL[h.action] ?? h.action}</Badge></td><td>{h.actor_name ?? "-"}</td></tr>))}</tbody>
        </table>
      </Card>
      {pages > 1 && <nav aria-label="페이지" className="flex items-center justify-center gap-2 text-sm"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>이전</Button>
        <span className="tabular-nums">{page} / {pages}</span><Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>다음</Button></nav>}
    </div>
  );
}
