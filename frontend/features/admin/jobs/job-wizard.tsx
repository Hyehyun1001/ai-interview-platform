"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { applyTemplate, closeJob, createJob, createTemplate, listTemplates, noteKeys, useMetrics, generateBank, getBank, getJob, jobKeys, publishJob, putFollowup, putQuestions, putWeights, updateJob, type JobOut } from "../api";
import { DEFAULT_WEIGHTS, MAX_QUESTIONS, WEIGHT_KEYS, WEIGHT_LABELS, buildChecklist, canPublish, cutoffBands, equalWeights, isForbiddenQuestion, lockCodeQuality,
  weightsDelta, weightsSum, type WeightKey } from "./wizard-logic";

const STEPS = ["기본 정보", "면접 모듈·질문", "가중치·꼬리질문·Guardrail", "검토·게시"] as const;
const input = "h-10 w-full rounded border border-border bg-surface px-3 text-sm";
const toLocal = (iso?: string | null) => (iso ? new Date(new Date(iso).getTime() - new Date(iso).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "");
const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : "저장하지 못했어요");

export function JobWizard({ jobId }: { jobId?: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const [step, setStep] = useState<number>(Math.min(4, Math.max(1, Number(params.get("step") ?? 1))));
  const q = useQuery({ queryKey: jobKeys.one(jobId ?? "new"), queryFn: () => getJob(jobId!), enabled: !!jobId, retry: 1, refetchOnWindowFocus: false });
  const job = q.data;
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [tplOpen, setTplOpen] = useState(false);

  const refresh = (j: JobOut) => { qc.setQueryData(jobKeys.one(j.id), j); void qc.invalidateQueries({ queryKey: jobKeys.list }); setSavedAt(new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })); };
  async function run<T>(fn: () => Promise<T>): Promise<T | null> {
    setSaving(true);
    try { return await fn(); } catch (e) { toast.error(errMsg(e)); return null; } finally { setSaving(false); }
  }
  const go = (n: number) => { setStep(n); if (jobId) router.replace(`/admin/jobs/${jobId}/edit?step=${n}`); };

  if (jobId && q.isPending) return <Skeleton className="h-96" />;
  if (jobId && q.isError) return <Card><ErrorState message="공고를 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  const closed = job?.status === "closed";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-bold">{job ? job.title : "신규 공고 작성"}</h1>
        {job && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs">{job.status === "draft" ? "임시 저장" : job.status === "open" ? "게시 중" : "마감"}</span>}
        <span className="ml-auto text-xs text-muted" aria-live="polite">{savedAt ? `임시 저장됨 ${savedAt}` : ""}</span>
        {job?.status === "draft" && <Button variant="secondary" onClick={() => setTplOpen(true)} data-testid="template-load">템플릿 불러오기</Button>}
        {job && <Link href={`/admin/jobs/${job.id}/preview`} target="_blank" rel="noopener"><Button variant="secondary" data-testid="preview-btn">미리보기</Button></Link>}
      </div>
      {job && <TemplateDialog open={tplOpen} jobId={job.id} onClose={() => setTplOpen(false)} onApplied={(j) => { refresh(j); setTplOpen(false); toast.success("템플릿을 불러왔어요"); go(2); }} />}
      <ol className="flex flex-wrap gap-2" aria-label="진행 단계">
        {STEPS.map((s, i) => (
          <li key={s}><button type="button" disabled={!jobId && i > 0} aria-current={step === i + 1 ? "step" : undefined} onClick={() => go(i + 1)}
            className={cn("rounded border px-3 py-1.5 text-sm", step === i + 1 ? "border-primary bg-primary/10 font-semibold" : "border-border text-muted", "disabled:opacity-40")}>{i + 1}. {s}</button></li>
        ))}
      </ol>
      {closed && <p role="status" className="rounded bg-warning-bg p-3 text-sm text-warning">마감된 공고는 수정할 수 없습니다.</p>}
      <Card className="p-5">
        {step === 1 && <Step1 job={job} disabled={closed} saving={saving} onSave={async (body) => {
          const j = await run(() => (job ? updateJob(job.id, { ...body, updated_at: job.updated_at }) : createJob(body)));
          if (!j) return;
          refresh(j);
          if (!job) router.replace(`/admin/jobs/${j.id}/edit?step=2`); else go(2);
          setStep(2);
        }} />}
        {step === 2 && job && <Step2 key={job.updated_at} job={job} disabled={closed} saving={saving} onChange={refresh} run={run} onNext={() => go(3)} onPrev={() => go(1)} />}
        {step === 3 && job && <Step3 key={job.updated_at} job={job} disabled={closed} saving={saving} onChange={refresh} run={run} onNext={() => go(4)} onPrev={() => go(2)} />}
        {step === 4 && job && <Step4 job={job} disabled={closed} saving={saving} run={run} go={go} onPublished={(j) => { refresh(j); toast.success("공고를 게시했어요"); router.push("/admin/jobs"); }}
          onClosed={(j) => { refresh(j); toast.success("공고를 마감했어요"); }} />}
        {step > 1 && !job && <p className="text-sm text-muted">먼저 기본 정보를 저장해 주세요.</p>}
      </Card>
    </div>
  );
}

type RunFn = <T>(fn: () => Promise<T>) => Promise<T | null>;
interface StepProps { job: JobOut; disabled: boolean; saving: boolean; onChange: (j: JobOut) => void; run: RunFn; onNext: () => void; onPrev: () => void }

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="block text-sm"><span className="mb-1 block font-medium">{label}</span>{children}{hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}</label>;
}

function Step1({ job, disabled, saving, onSave }: { job?: JobOut; disabled: boolean; saving: boolean; onSave: (b: Record<string, unknown>) => Promise<void> }) {
  const [f, setF] = useState({ title: job?.title ?? "", job_category: job?.job_category ?? "", headcount: job?.headcount ?? ("" as number | ""), deadline: toLocal(job?.deadline_at),
    duties: job?.duties ?? "", requirements: job?.requirements ?? "", preferred: job?.preferred ?? "", contact_email: job?.contact_email ?? "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const past = f.deadline !== "" && new Date(f.deadline).getTime() <= Date.now();
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (!f.title.trim()) { toast.error("공고 제목을 입력해 주세요"); return; }
      void onSave({ title: f.title.trim(), job_category: f.job_category || null, headcount: f.headcount === "" ? null : Number(f.headcount), deadline_at: f.deadline ? new Date(f.deadline).toISOString() : null,
        duties: f.duties || null, requirements: f.requirements || null, preferred: f.preferred || null, contact_email: f.contact_email || null }); }}>
      <Field label="공고 제목 *"><input className={input} value={f.title} onChange={set("title")} disabled={disabled} maxLength={200} /></Field>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="직무 카테고리 *"><select className={input} value={f.job_category} onChange={set("job_category")} disabled={disabled}><option value="">선택</option>{["개발", "디자인", "기획", "마케팅", "영업", "경영지원"].map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="모집 정원 *"><input className={input} type="number" min={1} value={f.headcount} onChange={set("headcount")} disabled={disabled} /></Field>
        <Field label="마감일 *"><input className={input} type="datetime-local" value={f.deadline} onChange={set("deadline")} disabled={disabled} aria-invalid={past} />{past && <span role="alert" className="text-xs text-danger">마감일은 미래여야 해요</span>}</Field>
      </div>
      <Field label="주요 업무 *" hint="주요 업무·지원 요건은 AI 질문 생성의 근거(JD)로 사용됩니다."><textarea className={cn(input, "h-28 py-2")} value={f.duties} onChange={set("duties")} disabled={disabled} /></Field>
      <Field label="지원 요건 *"><textarea className={cn(input, "h-28 py-2")} value={f.requirements} onChange={set("requirements")} disabled={disabled} /></Field>
      <Field label="우대 사항"><textarea className={cn(input, "h-20 py-2")} value={f.preferred} onChange={set("preferred")} disabled={disabled} /></Field>
      <Field label="담당자 문의 이메일"><input className={input} type="email" value={f.contact_email} onChange={set("contact_email")} disabled={disabled} /></Field>
      <div className="flex justify-end"><Button type="submit" loading={saving} disabled={disabled}>저장하고 다음 ›</Button></div>
    </form>
  );
}

interface Row { text: string; category: string; time: string }

function Step2({ job, disabled, saving, onChange, run, onNext, onPrev }: StepProps) {
  const metrics = useMetrics();
  const sandboxOff = metrics.data?.sandbox_enabled === false;  // 실행 환경이 꺼져 있으면 코딩테스트를 켤 수 없다 (UI_SPEC §4.7)
  const [coding, setCoding] = useState(job.coding_test_enabled);
  const [codingMin, setCodingMin] = useState(job.coding_test_time_limit_sec ? String(Math.round(job.coding_test_time_limit_sec / 60)) : "");
  const [limit, setLimit] = useState(String(job.answer_time_limit_sec ?? 120));
  const [rows, setRows] = useState<Row[]>(() => Array.from({ length: MAX_QUESTIONS }, (_, i) => { const q = job.questions[i]; return { text: q?.text ?? "", category: q?.category ?? "", time: q?.time_limit_sec ? String(q.time_limit_sec) : "" }; }));
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const bank = useQuery({ queryKey: jobKeys.bank(job.id), queryFn: () => getBank(job.id), refetchInterval: (s) => (s.state.data?.status === "queued" || s.state.data?.status === "running" ? 2000 : false), retry: 1 });
  const filled = rows.filter((r) => r.text.trim());
  const forbidden = rows.map((r) => isForbiddenQuestion(r.text));

  async function save() {
    if (coding && !Number(codingMin)) { toast.error("코딩테스트 제한시간을 입력해 주세요"); return false; }
    if (forbidden.some(Boolean)) { toast.error("채용 공정성 정책에 따라 사용할 수 없는 질문이 있어요"); return false; }
    const a = await run(() => updateJob(job.id, { answer_time_limit_sec: Number(limit) || null, coding_test_enabled: coding, coding_test_time_limit_sec: coding ? Number(codingMin) * 60 : null, updated_at: job.updated_at }));
    if (!a) return false;
    const ok = await run(() => putQuestions(job.id, filled.map((r) => ({ text: r.text.trim(), category: r.category || null, time_limit_sec: r.time ? Number(r.time) : null }))));
    if (!ok) return false;
    onChange({ ...a, questions: ok.map((x) => x), updated_at: a.updated_at } as JobOut);
    void bank.refetch();
    return true;
  }
  const addToSet = () => {
    const chosen = (bank.data?.items ?? []).filter((i) => picked.has(i.id));
    const next = rows.map((r) => ({ ...r }));
    let added = 0;
    for (const c of chosen) { const slot = next.find((r) => !r.text.trim()); if (!slot) { toast.warning("질문은 최대 10개까지 등록할 수 있어요"); break; } slot.text = c.text; slot.category = c.category ?? ""; added++; }
    setRows(next); setPicked(new Set()); if (added) toast.info(`${added}개를 세트에 추가했어요 (저장 필요)`);
  };
  const busy = bank.data?.status === "queued" || bank.data?.status === "running";
  return (
    <div className="space-y-6">
      <section className="space-y-3"><h2 className="font-semibold">면접 모듈</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="답변 기본 제한시간(초)"><input className={input} type="number" min={30} max={600} value={limit} onChange={(e) => setLimit(e.target.value)} disabled={disabled} /></Field>
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={coding} onChange={(e) => setCoding(e.target.checked)} disabled={disabled || (sandboxOff && !coding)} data-testid="coding-toggle" />코딩테스트 사용{sandboxOff && <span className="text-xs text-muted"> (실행 환경 비활성: 서버의 SANDBOX_ENABLED 를 켜야 해요)</span>}</label>
          <Field label="코딩테스트 제한시간(분)"><input className={input} type="number" min={5} value={codingMin} onChange={(e) => setCodingMin(e.target.value)} disabled={disabled || !coding} /></Field>
        </div></section>
      <section className="space-y-2"><div className="flex items-center justify-between"><h2 className="font-semibold">질문 세트 (최대 10개)</h2>
        <button type="button" className="text-sm text-primary" disabled={disabled} onClick={() => setRows(rows.map(() => ({ text: "", category: "", time: "" })))}>초기화</button></div>
        <ol className="space-y-2">{rows.map((r, i) => (
          <li key={i} className="grid grid-cols-[2rem_1fr_7rem_5rem] items-start gap-2">
            <span className="pt-2 text-sm text-muted">{i + 1}</span>
            <div><input className={cn(input, forbidden[i] && "border-danger")} aria-label={`질문 ${i + 1}`} placeholder="비워두면 직무 맞춤 질문이 자동 생성돼요" maxLength={200} value={r.text} disabled={disabled}
              onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />{forbidden[i] && <span role="alert" className="text-xs text-danger">채용 공정성 정책에 따라 사용할 수 없는 질문입니다</span>}</div>
            <input className={input} aria-label={`질문 ${i + 1} 분야`} placeholder="분야" value={r.category} disabled={disabled} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, category: e.target.value } : x)))} />
            <input className={input} aria-label={`질문 ${i + 1} 제한(초)`} placeholder="초" type="number" value={r.time} disabled={disabled} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, time: e.target.value } : x)))} />
          </li>))}</ol>
        <p className="text-xs text-muted">등록 {filled.length} / 10 · 빈칸은 면접 시 자동 생성돼요</p></section>
      <section className="space-y-2"><div className="flex items-center justify-between"><h2 className="font-semibold">AI 질문 뱅크 (JD 기반 후보)</h2>
        <Button variant="secondary" loading={busy} disabled={disabled || busy} onClick={() => void run(async () => { await generateBank(job.id); void bank.refetch(); })}>✨ JD 기반 질문 추출</Button></div>
        <p role="status" className="text-sm text-muted" data-testid="bank-status">{bank.data ? ({ none: "아직 추출하지 않았어요", queued: "⏳ 추출 대기 중…", running: "⏳ 추출 중… (최대 1분)", done: `후보 ${bank.data.items.length}개`, failed: bank.data.message ?? "추출에 실패했어요" })[bank.data.status] : ""}</p>
        {bank.data?.items.length ? <><ul className="max-h-64 space-y-1 overflow-auto rounded border border-border p-2">{bank.data.items.map((i) => (
          <li key={i.id}><label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={picked.has(i.id)} onChange={(e) => { const n = new Set(picked); if (e.target.checked) n.add(i.id); else n.delete(i.id); setPicked(n); }} />
            <span className="flex-1">{i.text}</span><span className="text-xs text-muted">{i.category}</span></label></li>))}</ul>
          <Button variant="secondary" disabled={!picked.size || disabled} onClick={addToSet}>선택 {picked.size}개 세트에 추가 ›</Button></> : null}</section>
      <div className="flex justify-between"><Button variant="secondary" onClick={onPrev}>‹ 이전</Button><Button loading={saving} disabled={disabled} onClick={async () => { if (await save()) onNext(); }}>저장하고 다음 ›</Button></div>
    </div>
  );
}

function Step3({ job, disabled, saving, onChange, run, onNext, onPrev }: StepProps) {
  const [w, setW] = useState<Record<WeightKey, number>>({ ...DEFAULT_WEIGHTS, ...job.weights.weights });
  const [gaze, setGaze] = useState(job.weights.gaze_penalty_enabled);
  const [cutoff, setCutoff] = useState(job.weights.cutoff_score == null ? "" : String(job.weights.cutoff_score));
  const [margin, setMargin] = useState(String(job.weights.cutoff_margin));
  const [fr, setFr] = useState({ ...job.followup_rules });
  const coding = job.coding_test_enabled;
  const sum = weightsSum(w), delta = weightsDelta(w);
  const bands = useMemo(() => cutoffBands(cutoff === "" ? null : Number(cutoff), Number(margin) || 0), [cutoff, margin]);
  useEffect(() => { setW((cur) => lockCodeQuality(cur, coding)); }, [coding]);
  async function save() {
    if (sum !== 100) return false;
    const a = await run(() => putWeights(job.id, { weights: w, gaze_penalty_enabled: gaze, cutoff_score: cutoff === "" ? null : Number(cutoff), cutoff_margin: Number(margin) || 0 }));
    if (!a) return false;
    const b = await run(() => putFollowup(job.id, fr));
    if (!b) return false;
    onChange({ ...job, weights: a, followup_rules: b });
    return true;
  }
  return (
    <div className="space-y-6">
      <section className="space-y-2"><div className="flex items-center justify-between"><h2 className="font-semibold">평가 항목 가중치 (합계 100)</h2>
        <span role="status" data-testid="weights-sum" className={cn("rounded-full px-2 py-0.5 text-sm font-semibold", sum === 100 ? "bg-success-bg text-success" : "bg-danger-bg text-danger")}>현재 합계 {sum}{sum === 100 ? " ✔" : delta > 0 ? ` (+${delta} 필요)` : ` (${-delta} 초과)`}</span></div>
        {WEIGHT_KEYS.map((k) => { const off = k === "code_quality" && !coding; return (
          <div key={k} className="grid grid-cols-[8rem_1fr_5rem] items-center gap-3 text-sm"><span>{WEIGHT_LABELS[k]}</span>
            <input type="range" min={0} max={100} step={5} value={w[k]} disabled={disabled || off} aria-label={`${WEIGHT_LABELS[k]} 슬라이더`} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} />
            <input className={input} type="number" min={0} max={100} value={w[k]} disabled={disabled || off} aria-label={`${WEIGHT_LABELS[k]} 가중치`} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} /></div>); })}
        <div className="flex gap-3 text-sm"><button type="button" className="text-primary" disabled={disabled} onClick={() => setW(equalWeights(coding))}>자동 균등 분배</button>
          <button type="button" className="text-primary" disabled={disabled} onClick={() => setW(lockCodeQuality({ ...DEFAULT_WEIGHTS }, coding))}>기본값으로</button></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={gaze} disabled={disabled} onChange={(e) => setGaze(e.target.checked)} />시선 이탈 감점 적용 (최대 5점) <span className="text-xs text-muted">참고 지표로만 사용하며 부정행위 판단 기준이 아닙니다</span></label></section>
      <section className="space-y-2"><h2 className="font-semibold">합격 기준 점수 (AI 예상 합불용, 선택)</h2>
        <div className="grid gap-4 sm:grid-cols-2"><Field label="합격선(cutoff) 0~100"><input className={input} type="number" min={0} max={100} value={cutoff} disabled={disabled} onChange={(e) => setCutoff(e.target.value)} /></Field>
          <Field label="경계 폭(margin) 0~20"><input className={input} type="number" min={0} max={20} value={margin} disabled={disabled} onChange={(e) => setMargin(e.target.value)} /></Field></div>
        <p className="text-sm" data-testid="cutoff-preview">{bands ? `${bands.pass}점 이상 🟢합격권 · ${bands.borderlineFrom}~${bands.pass - 0.1}점 🟡경계 · ${bands.borderlineFrom}점 미만 🔴미달` : "미입력 시 \"참고 불가\""}</p>
        <p className="text-xs text-muted">참고 지표이며 지원자에게는 보이지 않습니다. 변경하면 리포트가 끝난 지원자의 예상 합불이 다시 계산됩니다(점수는 그대로).</p></section>
      <section className="space-y-2"><h2 className="font-semibold">AI 꼬리질문 규칙</h2>
        <div className="flex flex-wrap gap-4 text-sm">{([["trigger_ambiguous", "답변이 모호할 때"], ["trigger_contradiction", "이력서와 모순될 때"], ["trigger_stt_unclear", "음성 인식이 불분명할 때"]] as const).map(([k, l]) => (
          <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={fr[k]} disabled={disabled} onChange={(e) => setFr({ ...fr, [k]: e.target.checked })} />{l}</label>))}</div>
        <Field label="최대 횟수 (1~4)"><select className={cn(input, "w-24")} value={fr.max_followups} disabled={disabled} onChange={(e) => setFr({ ...fr, max_followups: Number(e.target.value) })}>{[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}</select></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={fr.guardrail_strict} disabled={disabled} onChange={(e) => { if (!e.target.checked && !window.confirm("Grounding을 끄면 근거 없는 질문이 생성될 수 있습니다. 끄시겠어요?")) return; setFr({ ...fr, guardrail_strict: e.target.checked }); }} />
          답변 키워드 기반 근거(Grounding) 질문만 생성 (권장)</label>
        <p className="text-xs text-muted">3회 검증에 실패하면 꼬리질문은 생략하고 다음 질문으로 진행됩니다. 출력 규격(JSON) 강제는 항상 켜져 있습니다.</p></section>
      <div className="flex justify-between"><Button variant="secondary" onClick={onPrev}>‹ 이전</Button><Button loading={saving} disabled={disabled || sum !== 100} onClick={async () => { if (await save()) onNext(); }}>저장하고 다음 ›</Button></div>
    </div>
  );
}

function Step4({ job, disabled, saving, run, go, onPublished, onClosed }: { job: JobOut; disabled: boolean; saving: boolean; run: RunFn; go: (n: number) => void; onPublished: (j: JobOut) => void; onClosed: (j: JobOut) => void }) {
  const pool = job.questions.length + job.bank_count;
  const list = buildChecklist(job, pool);
  const ok = canPublish(list);
  const [asTemplate, setAsTemplate] = useState(false);
  const [tplName, setTplName] = useState("");
  const qc = useQueryClient();
  async function publish() {
    if (asTemplate && !tplName.trim()) { toast.error("템플릿 이름을 입력해 주세요"); return; }
    try {
      const published = await publishJob(job.id);
      if (asTemplate) {  // 게시가 성공한 뒤에만 템플릿으로 저장한다. 템플릿 저장 실패가 게시를 되돌리지는 않는다.
        try { await createTemplate(job.id, tplName.trim()); void qc.invalidateQueries({ queryKey: noteKeys.templates }); toast.success("템플릿으로 저장했어요"); }
        catch (e) { toast.error(e instanceof ApiError && e.code === "TEMPLATE_NAME_EXISTS" ? "같은 이름의 템플릿이 있어 게시만 완료했어요" : "템플릿 저장에 실패해 게시만 완료했어요"); }
      }
      onPublished(published);
    } catch (e) {
      if (e instanceof ApiError && e.code === "SANDBOX_DISABLED") toast.error("코딩테스트 실행 환경이 꺼져 있어 게시할 수 없어요. 코딩테스트를 끄거나 서버 설정을 확인하세요");
      else
      if (e instanceof ApiError && e.code === "QUESTION_POOL_INSUFFICIENT") toast.error(`질문이 ${String(e.details.needed)}개 더 필요해요. [JD 기반 질문 추출] 또는 직접 입력해 주세요`);
      else if (e instanceof ApiError && e.code === "PUBLISH_VALIDATION") toast.error(`누락된 항목이 있어요: ${(e.details.missing as string[]).join(", ")}`);
      else toast.error(errMsg(e));
    }
  }
  return (
    <div className="space-y-4">
      <h2 className="font-semibold">요약 체크리스트</h2>
      <ul className="space-y-2" data-testid="checklist">{list.map((i) => (
        <li key={i.key} className="flex items-center gap-2 text-sm"><span aria-hidden>{i.ok ? "✔" : i.level === "advice" ? "⚠" : "✕"}</span><span className={cn(!i.ok && i.level === "required" && "text-danger")}>{i.label}</span>
          {!i.ok && <button type="button" className="text-primary" onClick={() => go(i.step)}>{i.level === "advice" ? "설정하러 가기" : `${i.step}단계로`}</button>}</li>))}</ul>
      {job.status === "draft" && (
        <div className="space-y-2 rounded border border-border p-3">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={asTemplate} onChange={(e) => setAsTemplate(e.target.checked)} disabled={disabled} data-testid="save-template" />이 설정을 템플릿으로 저장</label>
          {asTemplate && <label className="block text-sm">템플릿 이름<input className={input} value={tplName} maxLength={100} onChange={(e) => setTplName(e.target.value)} data-testid="template-name" /></label>}
        </div>
      )}
      <div className="flex justify-end gap-2">
        {job.status === "open" && <Button variant="danger" loading={saving} onClick={() => { if (window.confirm("공고를 마감할까요? 다시 열 수 없습니다.")) void run(() => closeJob(job.id)).then((j) => j && onClosed(j)); }}>공고 마감</Button>}
        {job.status === "draft" && <Button disabled={!ok || disabled} onClick={() => void publish()} data-testid="publish-btn">공고 게시</Button>}
      </div>
    </div>
  );
}

function TemplateDialog({ open, jobId, onClose, onApplied }: { open: boolean; jobId: string; onClose: () => void; onApplied: (j: JobOut) => void }) {
  const q = useQuery({ queryKey: noteKeys.templates, queryFn: listTemplates, enabled: open, retry: 1 });
  const [pick, setPick] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setPick(null); }, [open]);
  async function apply() {
    if (!pick) return;
    if (!window.confirm("현재 입력한 내용(질문·가중치·모듈 설정 포함)이 템플릿 내용으로 덮어써집니다. 계속할까요?")) return;
    setBusy(true);
    try { onApplied(await applyTemplate(jobId, pick)); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  }
  return (
    <Modal open={open} title="템플릿 불러오기" onClose={() => { if (!busy) onClose(); }}>
      <div className="space-y-3">
        {q.isPending && <Skeleton className="h-20" />}
        {q.isError && <ErrorState message="템플릿을 불러오지 못했어요" onRetry={() => void q.refetch()} />}
        {q.data && q.data.length === 0 && <p className="text-sm text-muted" data-testid="template-empty">저장된 템플릿이 없어요. 공고를 게시할 때 "템플릿으로 저장"을 선택하면 여기에 나타나요.</p>}
        {q.data && q.data.length > 0 && (
          <ul className="space-y-1" role="radiogroup" aria-label="템플릿 목록">
            {q.data.map((t) => (
              <li key={t.id}><label className={cn("flex cursor-pointer items-center gap-2 rounded border p-2 text-sm", pick === t.id ? "border-primary bg-primary/5" : "border-border")}>
                <input type="radio" name="tpl" checked={pick === t.id} onChange={() => setPick(t.id)} />
                <span className="font-medium">{t.name}</span><span className="text-xs text-muted">{t.title} · 질문 {t.question_count}개{t.coding_test_enabled ? " · 코딩테스트" : ""}</span>
              </label></li>
            ))}
          </ul>
        )}
        <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose} disabled={busy}>취소</Button><Button onClick={() => void apply()} disabled={!pick} loading={busy} data-testid="template-apply">불러오기</Button></div>
      </div>
    </Modal>
  );
}
