import { Briefcase, Building2, CalendarClock, Code2, FileText, Lock, Mail, MapPin, MonitorCheck, Mic, Trophy, Users, Wallet, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Badge, Card } from "@/components/ui/primitives";
import { cn, ddayLabel } from "@/lib/utils";
import { DDayBadge } from "./job-list";
import { EMPLOYMENT_LABEL, formatDeadline, maxInterviewMinutes, toBullets } from "./logic";

/** 화면이 쓰는 공고 정보. 지원자 상세(JobDetail)와 담당자 미리보기(JobOut)가 같은 모양으로 변환해 같은 화면을 그린다. */
export interface JobView {
  title: string; company?: string | null; category?: string | null; deadline?: string | null; headcount?: number | null;
  duties?: string | null; requirements?: string | null; preferred?: string | null; contactEmail?: string | null;
  answerLimitSec?: number | null; questionCount?: number | null; maxFollowups?: number | null;
  codingEnabled: boolean; codingLimitSec?: number | null;
  workLocation?: string | null; employmentType?: string | null; salaryText?: string | null; benefits?: string | null; notice?: string | null;
}

function Bullets({ text }: { text?: string | null }) {
  const items = toBullets(text);
  if (items.length === 0) return null;
  // 담당자가 입력한 텍스트이므로 HTML 로 해석하지 않는다(XSS 방지). 한 줄이어도 다른 항목과 모양을 맞춰 목록으로 보여 준다.
  return <ul className="space-y-1.5 text-sm leading-relaxed">{items.map((t, i) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" aria-hidden /><span>{t}</span></li>)}</ul>;
}

function Section({ title, text }: { title: string; text?: string | null }) {
  if (toBullets(text).length === 0) return null;
  return <section className="space-y-2"><h2 className="text-base font-bold">{title}</h2><Bullets text={text} /></section>;
}

function Fact({ Icon, label, children }: { Icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-muted"><Icon className="h-4 w-4" aria-hidden /></span>
      <div className="min-w-0"><dt className="text-xs text-muted">{label}</dt><dd className="text-sm font-medium">{children}</dd></div>
    </div>
  );
}

export function processSteps(v: Pick<JobView, "codingEnabled" | "codingLimitSec" | "questionCount" | "maxFollowups" | "answerLimitSec">): { title: string; desc: string }[] {
  const steps = [
    { title: "지원서 제출", desc: "개인정보 활용에 동의하고 이력서를 PDF로 올리거나 직접 작성해요." },
    { title: "사전 환경 점검", desc: "카메라·마이크·스피커가 잘 동작하는지 3단계로 확인해요." },
    { title: "AI 음성 면접", desc: `AI 면접관이 질문하고 음성으로 답해요${v.questionCount ? ` (질문 ${v.questionCount}개` : ""}${v.questionCount && v.maxFollowups ? ` + 꼬리질문 최대 ${v.maxFollowups}회` : ""}${v.questionCount ? ")" : ""}.` },
  ];
  if (v.codingEnabled) steps.push({ title: "코딩테스트", desc: `면접 질문이 끝나면 이어서 진행해요${v.codingLimitSec ? ` (제한시간 ${Math.round(v.codingLimitSec / 60)}분)` : ""}. 제출한 코드에 대한 질문이 이어질 수 있어요.` });
  steps.push({ title: "결과 확인", desc: "AI 평가 리포트는 면접이 끝나면 마이페이지에서 볼 수 있고, 합격 여부는 담당자가 확정한 뒤 안내돼요." });
  return steps;
}

/** APP-03 공고 상세 본문. `action` 은 사이드 카드와 모바일 하단 고정 영역에 나오는 지원 버튼 영역이다. */
export function JobBody({ job, action, statusBadge, banner, compact = false }: { job: JobView; action: ReactNode; statusBadge?: ReactNode; banner?: ReactNode; compact?: boolean }) {
  const closed = ddayLabel(job.deadline).tone === "closed";
  const maxMin = maxInterviewMinutes(job.questionCount, job.maxFollowups, job.answerLimitSec);
  const steps = processSteps(job);
  return (
    <article className={cn("space-y-6", !compact && "pb-20 lg:pb-0")}>
      {banner}
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {job.category && <Badge tone="info">{job.category}</Badge>}
          {job.codingEnabled && <Badge tone="warning" data-testid="coding-badge"><Code2 className="mr-1 inline h-3 w-3" aria-hidden />코딩테스트 진행</Badge>}
          {job.deadline ? <DDayBadge deadline={job.deadline} /> : <Badge tone="neutral">상시 모집</Badge>}
          {statusBadge}
        </div>
        <h1 className={cn("font-bold leading-tight", compact ? "text-xl" : "text-2xl sm:text-3xl")}>{job.title || <span className="text-muted">공고 제목</span>}</h1>
        {job.company && <p className="flex items-center gap-1.5 text-sm text-muted"><Building2 className="h-4 w-4" aria-hidden />{job.company}</p>}
      </header>

      <div className={cn("grid gap-6", !compact && "lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start")}>
        <div className="space-y-6">
          <Card className="space-y-6 p-6" data-testid="job-sections">
            <Section title="주요 업무" text={job.duties} />
            <Section title="지원 요건" text={job.requirements} />
            <Section title="우대 사항" text={job.preferred} />
            <Section title="복리후생" text={job.benefits} />
            {toBullets(job.duties).length + toBullets(job.requirements).length + toBullets(job.preferred).length + toBullets(job.benefits).length === 0 && <p className="text-sm text-muted">상세 내용이 아직 등록되지 않았어요.</p>}
          </Card>

          <Card className="p-6" data-testid="process">
            <h2 className="mb-4 text-base font-bold">채용 절차</h2>
            <ol className="space-y-0">
              {steps.map((s, i) => (
                <li key={s.title} className="relative flex gap-4 pb-5 last:pb-0" data-testid="process-step">
                  {i < steps.length - 1 && <span className="absolute left-[15px] top-8 h-[calc(100%-2rem)] w-px bg-border" aria-hidden />}
                  <span className="z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-fg" aria-hidden>{i + 1}</span>
                  <div className="min-w-0 pt-0.5"><p className="font-semibold">{s.title}{s.title === "코딩테스트" && <span className="ml-2 align-middle text-xs font-normal text-warning">이 공고만 해당</span>}</p><p className="mt-0.5 text-sm text-muted">{s.desc}</p></div>
                </li>
              ))}
            </ol>
          </Card>

          {toBullets(job.notice).length > 0 && <Card className="space-y-2 p-6" data-testid="notice"><h2 className="text-base font-bold">전형 안내 · 유의 사항</h2><Bullets text={job.notice} /></Card>}

          <Card className="space-y-3 p-6" data-testid="guide">
            <h2 className="text-base font-bold">면접 전에 확인해 주세요</h2>
            <ul className="space-y-2 text-sm">
              <li className="flex gap-2"><MonitorCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />카메라·마이크·스피커가 있는 PC에서 최신 Chrome 브라우저로 접속해 주세요.</li>
              <li className="flex gap-2"><Mic className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />주변이 조용한 곳에서 진행해 주세요. 답변은 음성으로 인식되고, 시선은 화면을 보고 있는지만 브라우저에서 분석해요.</li>
              {job.codingEnabled && <li className="flex gap-2"><Code2 className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />코딩테스트는 Python · Java · JavaScript 중에서 고를 수 있고, 코드는 외부 네트워크가 없는 격리된 환경에서 실행돼요. 제출은 한 번만 할 수 있어요.</li>}
              <li className="flex gap-2"><Lock className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />AI 면접은 기업 내부망 서버에서만 처리됩니다. 음성·영상·이력서도 내부망에만 저장되고 외부 서비스로 전송되지 않아요.</li>
            </ul>
          </Card>
        </div>

        <aside className={cn("space-y-4", !compact && "max-lg:order-first lg:sticky lg:top-20", compact && "order-first")} aria-label="공고 요약">
          <Card className="space-y-4 p-5">
            <dl className="space-y-4">
              <Fact Icon={CalendarClock} label="접수 마감"><span data-testid="fact-deadline">{formatDeadline(job.deadline).replace(/^~ /, "")}{job.deadline && !closed ? ` (${ddayLabel(job.deadline).label})` : ""}</span></Fact>
              {job.headcount ? <Fact Icon={Users} label="모집 인원">{job.headcount}명</Fact> : null}
              {job.employmentType ? <Fact Icon={Briefcase} label="고용 형태"><span data-testid="fact-employment">{EMPLOYMENT_LABEL[job.employmentType] ?? job.employmentType}</span></Fact> : null}
              {job.workLocation ? <Fact Icon={MapPin} label="근무지"><span data-testid="fact-location">{job.workLocation}</span></Fact> : null}
              {job.salaryText ? <Fact Icon={Wallet} label="급여"><span data-testid="fact-salary">{job.salaryText}</span></Fact> : null}
              <Fact Icon={FileText} label="면접 방식">
                AI 음성 면접{job.answerLimitSec ? <span className="block text-xs font-normal text-muted">질문당 답변 최대 {job.answerLimitSec}초{maxMin ? ` · 답변 시간 기준 최대 약 ${maxMin}분` : ""}</span> : null}
              </Fact>
              <Fact Icon={Trophy} label="코딩테스트"><span data-testid="fact-coding">{job.codingEnabled ? `있음${job.codingLimitSec ? ` (제한 ${Math.round(job.codingLimitSec / 60)}분)` : ""}` : "없음"}</span></Fact>
              {job.contactEmail ? <Fact Icon={Mail} label="문의"><span className="break-all">{job.contactEmail}</span></Fact> : null}
            </dl>
            {/* 지원 버튼은 DOM 에 하나만 둔다: 데스크톱에서는 이 카드 안, 모바일에서는 화면 아래에 고정되는 바 */}
            <div data-testid="cta" className={cn(!compact && "max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-20 max-lg:border-t max-lg:border-border max-lg:bg-surface max-lg:p-3 max-lg:shadow-[0_-4px_12px_rgba(0,0,0,0.06)]")}>{action}</div>
          </Card>
        </aside>
      </div>

    </article>
  );
}

