"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { useMyApplications, useMyResume } from "@/features/applicant/api";
import { STATUS_LABEL, continueTarget } from "@/features/jobs/logic";
import { ResumeRegistration } from "@/features/resume/resume-registration";
import { ProfileTab } from "./profile-tab";

const TABS = [{ id: "applications", label: "지원 현황" }, { id: "resume", label: "이력서·자소서" }, { id: "profile", label: "프로필 정보" }, { id: "calendar", label: "일정 (준비 중)" }] as const;
type TabId = (typeof TABS)[number]["id"];
const isTab = (v: string | null): v is TabId => TABS.some((t) => t.id === v);

/** APP-04 마이페이지. 탭 상태는 URL `?tab=` 로 유지한다 (UI_SPEC §4.4). */
export function MyPageView() {
  const sp = useSearchParams();
  const router = useRouter();
  const raw = sp.get("tab");
  const tab: TabId = isTab(raw) ? raw : "applications";
  const set = (t: TabId) => router.replace(`/mypage?tab=${t}`, { scroll: false });

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">마이페이지</h1>
      <div role="tablist" aria-label="마이페이지 탭" className="flex gap-1 border-b border-border">
        {TABS.map((t) => (
          <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} disabled={t.id === "calendar"} onClick={() => set(t.id)}
            className={cn("px-4 py-2 text-sm", tab === t.id ? "border-b-2 border-primary font-semibold" : "text-muted", t.id === "calendar" && "cursor-not-allowed opacity-50")}>{t.label}</button>
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
    <Card className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="applications-table">
        <thead className="border-b border-border text-left text-muted"><tr><th className="p-3">공고명</th><th className="p-3">지원일</th><th className="p-3">상태</th><th className="p-3">다음 액션</th></tr></thead>
        <tbody>
          {q.data.map((a) => {
            const next = continueTarget(a);
            return (
              <tr key={a.application_id} className="border-b border-border last:border-0">
                <td className="p-3 font-medium"><Link href={`/jobs/${a.job.id}`} className="hover:underline">{a.job.title}</Link></td>
                <td className="p-3 tabular-nums">{new Date(a.applied_at).toLocaleDateString("ko-KR")}</td>
                <td className="p-3"><Badge tone={a.status === "report_ready" ? "success" : "info"}>{STATUS_LABEL[a.status]}</Badge></td>
                <td className="p-3"><Link href={next.href}><Button variant="secondary">{next.label}</Button></Link></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
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
      <Card className="p-5"><ResumeRegistration key={q.data?.updated_at ?? "none"} registered={q.data ?? null} onSaved={() => undefined} /></Card>
    </div>
  );
}
