"use client";
import Link from "next/link";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { useMyApplications, useMyResume } from "@/features/applicant/api";
import { STATUS_LABEL, continueTarget } from "@/features/jobs/logic";
import { ResumeRegistration } from "@/features/resume/resume-registration";
import { ProfileTab } from "./profile-tab";

const TABS = [{ id: "applications", label: "지원 현황" }, { id: "resume", label: "이력서·자소서" }, { id: "profile", label: "프로필 정보" }] as const;
type TabId = (typeof TABS)[number]["id"];
const isTab = (v: string | null): v is TabId => TABS.some((t) => t.id === v);

export type MyPageTab = TabId;
export const parseMyPageTab = (v: string | null): MyPageTab | null => (isTab(v) ? v : null);

/** APP-04 마이페이지. 지원자 GNB 의 사람 아이콘을 누르면 오른쪽 사이드 패널로 열린다(MyPageDrawer). 탭 상태는 URL `?mypage=` 에 유지한다. */
export function MyPagePanel({ tab, onTab }: { tab: MyPageTab; onTab: (t: MyPageTab) => void }) {
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="마이페이지 탭" className="-mx-1 flex gap-1 overflow-x-auto border-b border-border px-1">
        {TABS.map((t) => (
          <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} onClick={() => onTab(t.id)}
            className={cn("shrink-0 whitespace-nowrap px-3 py-2 text-sm", tab === t.id ? "border-b-2 border-primary font-semibold" : "text-muted")}>{t.label}</button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "applications" && <ApplicationsTab />}
        {tab === "resume" && <ResumeTab />}
        {tab === "profile" && <ProfileTab />}
      </div>
    </div>
  );
}

function ApplicationsTab() {
  const q = useMyApplications();
  if (q.isError) return <Card><ErrorState message="지원 현황을 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (!q.data) return <Skeleton className="h-40" />;
  if (q.data.length === 0) return <Card><EmptyState title="아직 지원한 공고가 없어요" action={<Link href="/jobs"><Button>공고 보러가기</Button></Link>} /></Card>;
  return (
    <ul className="space-y-3" aria-label="지원 현황" data-testid="applications-list">
      {q.data.map((a) => {
        const next = continueTarget(a);
        return (
          <li key={a.application_id} data-testid="application-item">
            <Card className="space-y-2 p-4">
              <div className="flex items-start justify-between gap-2">
                <Link href={`/jobs/${a.job.id}`} className="font-semibold hover:underline">{a.job.title}</Link>
                <Badge tone={a.status === "report_ready" ? "success" : "info"}>{STATUS_LABEL[a.status]}</Badge>
              </div>
              <p className="text-xs text-muted">지원일 {new Date(a.applied_at).toLocaleDateString("ko-KR")}</p>
              <Link href={next.href} className="block"><Button variant="secondary" className="w-full">{next.label}</Button></Link>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

function ResumeTab() {
  const q = useMyResume();
  const apps = useMyApplications();
  if (q.isError) return <Card><ErrorState message="이력서를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (q.isLoading) return <Skeleton className="h-64" />;
  const interviewing = (apps.data ?? []).filter((a) => a.status === "interviewing");
  return (
    <div className="space-y-3">
      {!q.data && <Card className="p-4 text-sm" data-testid="resume-empty">아직 등록된 이력서가 없어요. PDF를 첨부하거나 직접 작성해 보세요.</Card>}
      {interviewing.length > 0 && <p role="note" className="rounded bg-info-bg p-3 text-sm text-info">면접이 진행 중인 지원 건({interviewing.map((a) => a.job.title).join(", ")})의 이력서는 지원 시점 그대로 유지되며 수정할 수 없어요.</p>}
      <ResumeRegistration key={q.data?.updated_at ?? "none"} registered={q.data ?? null} onSaved={() => undefined} />
    </div>
  );
}
