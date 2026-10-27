"use client";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, PencilLine } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { RESUME_KEY, saveMyResume, type ResumeOut } from "@/features/applicant/api";
import { FileDropzone } from "./file-dropzone";
import { OcrProgress } from "./ocr-progress";
import { ResumeEditor } from "./resume-editor";
import { basicInfoIssues, emptyResumeForm, isBasicInfoComplete, toFormValues, toResumeData, type ResumeFormValues } from "./schema";
import { useResumeExtraction } from "./use-resume-extraction";

/**
 * 마이페이지 이력서 등록·수정 (APP-04 이력서 탭, APP-01b 가입 직후 팝업 공용 — UI_SPEC §4.1.2, §4.4).
 * PDF 추출 결과는 폼에 채워질 뿐 저장은 [저장] 을 눌러야 `PUT /me/resume` 으로 반영된다(PRD 10장 #11).
 * `requireComplete`: 팝업은 기본 정보(성명 + 학력/경력 1건)를 채워야 저장, 마이페이지는 작성 중 저장을 허용한다.
 */
export function ResumeRegistration({ registered, onSaved, onCancel, requireComplete = false, cancelLabel = "취소" }: {
  registered: ResumeOut | null; onSaved: (saved: ResumeOut) => void; onCancel?: () => void; requireComplete?: boolean; cancelLabel?: string;
}) {
  const qc = useQueryClient();
  const hasData = !!registered?.data;
  const form = useForm<ResumeFormValues>({ defaultValues: hasData ? toFormValues(registered!.data) : emptyResumeForm() });
  const values = form.watch();
  const extraction = useResumeExtraction();
  const [view, setView] = useState<"choice" | "editor">(hasData ? "editor" : "choice");
  const [replacing, setReplacing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showIssues, setShowIssues] = useState(false);
  const saved = useRef(false);

  useEffect(() => {
    if (extraction.state.phase === "done") { form.reset(toFormValues(extraction.state.data), { keepDefaultValues: true }); form.trigger(); setView("editor"); setReplacing(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extraction.state.phase]);

  const dirty = (form.formState.isDirty || extraction.state.phase === "done") && !saved.current;
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const complete = isBasicInfoComplete(values);
  const issues = showIssues || (form.formState.isDirty && !complete) ? basicInfoIssues(values) : null;
  const canSave = view === "editor" && !busy && (!requireComplete || complete);

  async function save() {
    if (requireComplete && !complete) { setShowIssues(true); return; }
    setBusy(true);
    try {
      const out = await saveMyResume(toResumeData(form.getValues()));
      saved.current = true;
      void qc.invalidateQueries({ queryKey: RESUME_KEY });
      form.reset(toFormValues(out.data));
      toast.success("이력서를 저장했어요");
      onSaved(out);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "저장에 실패했어요. 다시 시도해 주세요.", e instanceof ApiError ? { code: e.code, requestId: e.requestId } : undefined);
    } finally { setBusy(false); }
  }

  const ex = extraction.state;
  const upload = (
    <div className="space-y-3">
      {(ex.phase === "idle" || ex.phase === "done") && <FileDropzone onFile={(f) => void extraction.start(f)} />}
      <OcrProgress state={ex} onCancel={extraction.cancel} onKeepWaiting={extraction.keepWaiting} onManual={() => { extraction.cancel(); setView("editor"); setReplacing(false); }} />
    </div>
  );

  return (
    <div className="space-y-4" data-testid="resume-registration">
      {view === "choice" ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-border p-4">
              <p className="flex items-center gap-2 font-semibold"><FileText className="h-5 w-5" aria-hidden />PDF 첨부</p>
              <p className="mb-3 mt-1 text-xs text-muted">OCR로 자동 입력 (PDF만 · 10MB 이하)</p>
              {upload}
            </div>
            <div className="flex flex-col rounded-lg border border-border p-4">
              <p className="flex items-center gap-2 font-semibold"><PencilLine className="h-5 w-5" aria-hidden />직접 작성</p>
              <p className="mb-3 mt-1 text-xs text-muted">PDF가 없다면 여기서 기본 정보를 입력하세요</p>
              <Button variant="secondary" className="mt-auto" onClick={() => setView("editor")}>직접 작성하기</Button>
            </div>
          </div>
          {onCancel && <div className="flex justify-end"><Button variant="ghost" onClick={onCancel}>{cancelLabel}</Button></div>}
        </>
      ) : (
        <>
          {hasData && (
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="text-muted">등록 상태: ● 등록됨 ({registered!.source === "pdf" ? "PDF 기반" : "직접 작성"}, 최종 수정 {new Date(registered!.updated_at).toLocaleDateString("ko-KR")})</span>
              <Button variant="secondary" onClick={() => setReplacing((v) => !v)}>{replacing ? "PDF 교체 닫기" : "PDF 교체"}</Button>
            </div>
          )}
          {(replacing || (ex.phase !== "idle" && ex.phase !== "done")) && upload}
          {ex.phase === "done" && <p role="status" className="rounded bg-info-bg p-3 text-sm text-info" data-testid="extracted-banner">자동 추출된 값입니다. 확인 후 수정하고 [저장] 을 누르세요.{ex.fellBack && " 이번 파일에서는 정보를 거의 찾지 못했어요. 직접 입력해 주세요."}</p>}
          <ResumeEditor form={form} issues={issues} />
          {requireComplete && !complete && <p className="text-sm text-warning" data-testid="basic-info-warning">⚠ 성명과 학력 또는 경력 1건 이상을 입력해야 저장할 수 있어요.</p>}
          <p className="text-xs text-muted">ⓘ 마이페이지 수정은 이미 지원한 건의 이력서에 영향을 주지 않습니다.</p>
          <div className="flex justify-end gap-2">
            {onCancel && <Button variant="ghost" onClick={onCancel} disabled={busy}>{cancelLabel}</Button>}
            <Button onClick={() => void save()} disabled={!canSave} loading={busy} data-testid="resume-save">저장</Button>
          </div>
        </>
      )}
    </div>
  );
}
