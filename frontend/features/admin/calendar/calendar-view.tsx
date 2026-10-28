"use client";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { listSchedules, scheduleKeys } from "../api";
import { ScheduleFormDialog } from "../dashboard/schedule-dialog";
import { TYPE_LABEL, addDays, eventsOn, monthGrid, rangeFor, sameDay, startOfDay, toLocalInput, weekDays, type Sched } from "./calendar-logic";

type View = "month" | "week" | "list";
const VIEWS: [View, string][] = [["month", "월"], ["week", "주"], ["list", "리스트"]];
const DOW = ["일", "월", "화", "수", "목", "금", "토"];
const TONE: Record<string, "info" | "success" | "warning" | "neutral"> = { interview1: "info", interview2: "success", doc_screen: "neutral", deadline: "warning" };
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });

/** ADM-07 면접 일정 캘린더: 월/주/리스트 보기, 일정 클릭=수정·삭제, 빈 날짜 클릭=그 날짜로 추가 (경량 자체 구현). */
export function CalendarView() {
  const [view, setView] = useState<View>("month");
  useEffect(() => { if (window.innerWidth < 768) setView("list"); }, []);  // 좁은 화면에서는 월 격자 대신 리스트가 읽기 쉽다
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()));
  const [editing, setEditing] = useState<Sched | null>(null);
  const [creating, setCreating] = useState<string | null>(null);   // 추가 모달: 기본 시작 일시
  const { from, to } = useMemo(() => rangeFor(view, anchor), [view, anchor]);
  const q = useQuery({ queryKey: scheduleKeys.range(from.toISOString(), to.toISOString()), queryFn: () => listSchedules(from.toISOString(), to.toISOString()), retry: 1 });
  const events = (q.data ?? []) as Sched[];
  const today = startOfDay(new Date());

  const move = (dir: -1 | 1) => setAnchor((a) => view === "month" ? new Date(a.getFullYear(), a.getMonth() + dir, 1) : addDays(a, dir * (view === "week" ? 7 : 30)));
  const title = view === "month" ? `${anchor.getFullYear()}년 ${anchor.getMonth() + 1}월` : view === "week" ? `${weekDays(anchor)[0]!.toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} 주` : "다가오는 일정 (60일)";
  const addAt = (d: Date) => setCreating(toLocalInput(new Date(d.getFullYear(), d.getMonth(), d.getDate(), 10, 0).toISOString()));

  const Chip = ({ e }: { e: Sched }) => (
    <button type="button" onClick={() => setEditing(e)} data-testid="schedule-chip" className="block w-full truncate rounded px-1 text-left text-xs hover:bg-surface-2" title={`${TYPE_LABEL[e.type]} · ${e.title}`}>
      <span className="mr-1 tabular-nums text-muted">{hhmm(e.starts_at)}</span>{e.title}
    </button>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xl font-bold">일정 관리</h2>
        <Button onClick={() => addAt(anchor)} data-testid="schedule-add"><Plus className="h-4 w-4" aria-hidden />일정 추가</Button>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div role="group" aria-label="보기 방식" className="flex rounded border border-border">
          {VIEWS.map(([v, l]) => <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)} className={cn("px-3 py-1.5 text-sm", view === v ? "bg-primary text-primary-fg" : "hover:bg-surface-2")}>{l}</button>)}
        </div>
        <div className="flex items-center gap-1">
          <Button variant="secondary" aria-label="이전" onClick={() => move(-1)}><ChevronLeft className="h-4 w-4" aria-hidden /></Button>
          <span className="min-w-36 text-center font-semibold" aria-live="polite" data-testid="cal-title">{title}</span>
          <Button variant="secondary" aria-label="다음" onClick={() => move(1)}><ChevronRight className="h-4 w-4" aria-hidden /></Button>
        </div>
        <Button variant="ghost" onClick={() => setAnchor(today)}>오늘</Button>
      </div>

      {q.isError ? <Card><ErrorState message="일정을 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>
        : q.isPending ? <Skeleton className="h-96" />
        : view === "month" ? (
          <Card className="overflow-x-auto p-0">
            <div className="grid min-w-[700px] grid-cols-7 border-b border-border text-center text-xs text-muted">{DOW.map((d) => <div key={d} className="py-1">{d}</div>)}</div>
            <div className="grid min-w-[700px] grid-cols-7" data-testid="month-grid">
              {monthGrid(anchor.getFullYear(), anchor.getMonth()).map((d) => {
                const evs = eventsOn(events, d);
                const inMonth = d.getMonth() === anchor.getMonth();
                return (
                  <div key={d.toISOString()} className={cn("min-h-24 border-b border-r border-border p-1", !inMonth && "bg-surface-2/50 text-muted")}>
                    <button type="button" onClick={() => addAt(d)} aria-label={`${d.getMonth() + 1}월 ${d.getDate()}일 일정 추가`} className={cn("mb-1 inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-xs hover:bg-surface-2", sameDay(d, today) && "bg-primary text-primary-fg hover:bg-primary")}>{d.getDate()}</button>
                    <div className="space-y-0.5">{evs.slice(0, 3).map((e) => <Chip key={e.id} e={e} />)}{evs.length > 3 && <p className="px-1 text-xs text-muted">+{evs.length - 3}건</p>}</div>
                  </div>
                );
              })}
            </div>
          </Card>
        ) : view === "week" ? (
          <div className="grid gap-2 md:grid-cols-7" data-testid="week-grid">
            {weekDays(anchor).map((d) => { const evs = eventsOn(events, d); return (
              <Card key={d.toISOString()} className={cn("min-h-32 p-2", sameDay(d, today) && "border-primary")}>
                <p className="mb-1 text-xs font-semibold">{d.getMonth() + 1}/{d.getDate()} ({DOW[d.getDay()]})</p>
                {evs.length === 0 ? <p className="text-xs text-muted">일정 없음</p> : <div className="space-y-0.5">{evs.map((e) => <Chip key={e.id} e={e} />)}</div>}
              </Card>); })}
          </div>
        ) : events.length === 0 ? <Card><EmptyState title="예정된 일정이 없어요" action={<Button onClick={() => addAt(today)}>일정 추가</Button>} /></Card> : (
          <Card className="divide-y divide-border p-0" data-testid="list-view">
            {[...events].sort((a, b) => a.starts_at.localeCompare(b.starts_at)).map((e) => (
              <button key={e.id} type="button" onClick={() => setEditing(e)} data-testid="schedule-chip" className="flex w-full items-center gap-3 p-3 text-left hover:bg-surface-2">
                <span className="w-36 text-sm tabular-nums text-muted">{new Date(e.starts_at).toLocaleDateString("ko-KR", { month: "short", day: "numeric", weekday: "short" })} {hhmm(e.starts_at)}</span>
                <Badge tone={TONE[e.type] ?? "neutral"}>{TYPE_LABEL[e.type] ?? e.type}</Badge><span className="font-medium">{e.title}</span>
              </button>))}
          </Card>
        )}
      <ScheduleFormDialog open={creating !== null || editing !== null} schedule={editing} defaultStart={creating ?? undefined} existing={events}
        onClose={() => { setCreating(null); setEditing(null); }} />
    </div>
  );
}
