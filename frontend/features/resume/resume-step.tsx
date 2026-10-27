"use client";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Badge, Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ApplyStepper } from "@/components/ui/stepper";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { MY_APPS_KEY, RESUME_KEY, confirmApplicationResume, createSession, saveMyResume, useMyApplications, useMyResume } from "@/features/applicant/api";
import { continueTarget } from "@/features/jobs/logic";
import { FileDropzone } from "./file-dropzone";
import { OcrProgress } from "./ocr-progress";
import { ResumeEditor } from "./resume-editor";
import { basicInfoIssues, emptyResumeForm, isBasicInfoComplete, toFormValues, toResumeData, type BasicInfoIssues, type ResumeFormValues } from "./schema";
import { useResumeExtraction } from "./use-resume-extraction";

type Source = "mypage" | "upload" | "manual";
const SOURCE_LABEL: Record<Source, string> = { mypage: "마이페이지 등록본 사용", upload: "PDF 새로 첨부 (PDF만)", manual: "직접 작성" };

/** APP-05 이력서 제출(지원 단계) — UI_SPEC §4.3. 서버 응답(BASIC_INFO_REQUIRED)이 최종 기준이다. */
export function ResumeStep({ applicationId }: { applicationId: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const apps = useMyApplications();
  const mine = useMyResume();
  const app = apps.data?.find((a) => a.application_id === applicationId);

  const form = useForm<ResumeFormValues>({ defaultValues: emptyResumeForm() });
  const values = form.watch();
  const extraction = useResumeExtraction();
  const [source, setSource] = useState<Source | null>(null);
  const [editingRegistered, setEditingRegistered] = useState(false);
  const [saveToMypage, setSaveToMypage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [serverIssues, setServerIssues] = useState<BasicInfoIssues | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const leaving = useRef(false);

  const registered = mine.data ?? null;
  const hasRegistered = !!registered?.data;

  // 초기 선택: 등록본이 있으면 등록본, 없으면 PDF 첨부 (UI_SPEC §4.3.4)
  useEffect(() => {
    if (source !== null || mine.isLoading) return;
    if (hasRegistered) { setSource("mypage"); form.reset(toFormValues(registered!.data)); } else setSource("upload");
  }, [source, mine.isLoading, hasRegistered, registered, form]);

  // 이미 진행 단계가 지난 지원 건은 해당 단계로 보낸다 (세션이 이미 있으면 이력서를 바꿀 수 없다)
  useEffect(() => {
    if (!app) return;
    if (app.status !== "applied" && !(app.status === "prepared" && !app.session_id)) { leaving.current = true; router.replace(continueTarget(app).href); }
  }, [app, router]);

  // 추출 완료 → 폼에 채운다. 추출하지 못한 값은 빈 칸으로 둔다.
  useEffect(() => {
    if (extraction.state.phase === "done") { form.reset(toFormValues(extraction.state.data)); setServerIssues(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extraction.state.phase]);

  // 입력 중 이탈 경고
  const dirty = form.formState.isDirty || extraction.state.phase === "done";
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty && !leaving.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const complete = isBasicInfoComplete(values);
  const liveIssues = useMemo(() => basicInfoIssues(values), [values]);
  const issues = serverIssues ?? (form.formState.isDirty && !complete ? liveIssues : null);

  function choose(next: Source) {
    if (next === source) return;
    setServerIssues(null);
    if (next === "mypage" && registered?.data) { form.reset(toFormValues(registered.data)); setEditingRegistered(false); }
    else if (next === "upload") { extraction.cancel(); form.reset(emptyResumeForm()); }
    else if (next === "manual" && source === "mypage") form.reset(emptyResumeForm());
    setSource(next);
  }
  function toManual() {
    extraction.cancel();
    setSource("manual");
    setTimeout(() => form.setFocus("name"), 0);
  }

  const showEditor = source === "manual" || (source === "mypage" && hasRegistered) || (source === "upload" && extraction.state.phase === "done");
  const registeredReadOnly = source === "mypage" && !editingRegistered;
  const canNext = !busy && showEditor && (source === "mypage" && registeredReadOnly ? !!registered?.basic_info_complete : complete);

  async function next() {
    if (!source) return;
    setBusy(true);
    try {
      const data = toResumeData(form.getValues());
      const effective: Source = source === "mypage" && editingRegistered ? "manual" : source;
      if (saveToMypage && effective !== "mypage") { await saveMyResume(data); void qc.invalidateQueries({ queryKey: RESUME_KEY }); }
      await confirmApplicationResume(applicationId, effective, effective === "mypage" ? undefined : data);
      await createSession(applicationId);
      void qc.invalidateQueries({ queryKey: MY_APPS_KEY });
      leaving.current = true;
      router.push(`/apply/${applicationId}/device-check`);
    } catch (e) {
      if (!(e instanceof ApiError)) { toast.error("요청에 실패했어요. 다시 시도해 주세요."); return; }
      if (e.code === "BASIC_INFO_REQUIRED" && e.status === 422) {
        setServerIssues(basicInfoIssues(form.getValues()));
        editorRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        toast.error(e.message, { code: e.code });
      } else if (e.code === "SESSION_ALREADY_CREATED") {
        leaving.current = true;
        router.push(`/apply/${applicationId}/device-check`);  // 이미 세션이 있으면 이어서 진행 (멱등)
      } else if (e.status === 409) {
        toast.error("지원 단계를 다시 확인해 주세요.", { code: e.code });
        if (app) router.push(`/jobs/${app.job.id}`);
      } else toast.error(e.message, { code: e.code, requestId: e.requestId });
    } finally { setBusy(false); }
  }

  if (apps.isError || (apps.data && !app)) return <Card className="mx-auto max-w-lg"><ErrorState message="지원 내역을 찾을 수 없어요" /><div className="pb-6 text-center"><Link href="/jobs" className="text-primary">공고 목록으로</Link></div></Card>;
  if (!app || source === null) return <div className="space-y-3" aria-busy><Skeleton className="h-8 w-80" /><Skeleton className="h-64 w-full" /></div>;
  const ex = extraction.state;

  return (
    <div className="space-y-6">
      <ApplyStepper current={2} />
      <header><p className="text-sm text-muted">지원 공고</p><h1 className="text-xl font-bold">{app.job.title}</h1></header>

      <Card className="space-y-4 p-5">
        <fieldset className="space-y-2">
          <legend className="font-bold">이력서 사용 방법을 선택하세요</legend>
          {(["mypage", "upload", "manual"] as Source[]).filter((s) => s !== "mypage" || hasRegistered).map((s) => (
            <label key={s} className="flex items-center gap-2 text-sm">
              <input type="radio" name="source" checked={source === s} onChange={() => choose(s)} className="h-4 w-4" />
              <span>{SOURCE_LABEL[s]}</span>
              {s === "mypage" && registered && <span className="text-xs text-muted">— 최종 수정 {new Date(registered.updated_at).toLocaleDateString("ko-KR")}</span>}
            </label>
          ))}
        </fieldset>

        {source === "upload" && (
          <div className="space-y-3">
            {(ex.phase === "idle" || ex.phase === "done") && <FileDropzone onFile={(f) => void extraction.start(f)} />}
            <OcrProgress state={ex} onCancel={extraction.cancel} onKeepWaiting={extraction.keepWaiting} onManual={toManual} />
            {ex.phase === "done" && (
              <p role="status" className="rounded bg-info-bg p-3 text-sm text-info" data-testid="extracted-banner">
                자동 추출된 값입니다. 확인 후 수정하세요.{ex.fellBack && " 이번 파일에서는 정보를 거의 찾지 못했어요. 직접 입력해 주세요."}
              </p>
            )}
          </div>
        )}

        {source === "mypage" && hasRegistered && (
          <div className="flex items-center gap-2">
            <Badge tone="info">등록본 미리보기</Badge>
            {registeredReadOnly ? <Button variant="secondary" onClick={() => setEditingRegistered(true)}>수정</Button> : <span className="text-xs text-muted">수정한 내용은 이번 지원에만 쓰입니다.</span>}
          </div>
        )}
      </Card>

      {showEditor && (
        <Card className="space-y-4 p-5" >
          <div ref={editorRef}>
            <h2 className="mb-3 font-bold">{source === "upload" ? "추출 정보 확인·수정" : "이력서 정보"}</h2>
            <ResumeEditor form={form} readOnly={registeredReadOnly} issues={issues} />
          </div>
          {!complete && !registeredReadOnly && (
            <p className="text-sm text-warning" data-testid="basic-info-warning">⚠ 필수 항목(성명, 학력 또는 경력 1건 이상)을 입력해야 다음 단계로 갈 수 있어요.</p>
          )}
          {!registeredReadOnly && (
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4" checked={saveToMypage} onChange={(e) => setSaveToMypage(e.target.checked)} />이 이력서를 마이페이지에도 저장</label>
          )}
        </Card>
      )}

      <footer className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/jobs/${app.job.id}`} className="inline-flex items-center gap-1 text-sm text-muted hover:text-text"><ArrowLeft className="h-4 w-4" aria-hidden />이전: 공고 상세</Link>
        <div className="flex items-center gap-2">
          {source === "upload" && <Button variant="ghost" onClick={toManual}>PDF 첨부 건너뛰기</Button>}
          <Button onClick={() => void next()} disabled={!canNext} loading={busy} data-testid="next-btn">다음: 장치 점검 ›</Button>
        </div>
      </footer>
      <p className="text-xs text-muted">* 건너뛰기는 PDF 첨부만 건너뜁니다. 기본 정보 작성은 건너뛸 수 없습니다.</p>
    </div>
  );
}
