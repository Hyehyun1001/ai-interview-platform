"use client";
import { useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { Loader2, Lock, Mic, Play, Send } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { codeKeys, runSamples, submitCode, useProblem, useResult, type CaseOut, type Language, type RunOut } from "./api";
import { MAX_FOLLOWUP_CHARS, MONACO_LANG, VERDICT_LABEL, codingStartedAt, formatClock, loadDraft, remainingMs, saveDraft, verdictTone } from "./coding-logic";
import { useInterviewStore } from "@/features/interview/store";

const MonacoEditor = dynamic(() => import("./monaco-editor"), { ssr: false, loading: () => <p className="p-3 text-sm text-muted">편집기를 불러오는 중…</p> });

/**
 * APP-07 코딩테스트 탭 (UI_SPEC §4.7). 질문이 모두 끝난 뒤(session_finished{next:"coding"}) 활성화되며 그 전에는 잠금이다.
 * 코드는 서버의 격리된 샌드박스에서만 실행된다. 제출 직후 오는 코드 꼬리질문(kind=code_followup)은 텍스트(채팅)로 답한다.
 */
export function CodingPane({ sessionId, onText, onFinish, finishing }: {
  sessionId: string; onText: (turnId: string, text: string) => boolean; onFinish: () => void; finishing: boolean;
}) {
  const qc = useQueryClient();
  const problem = useProblem(sessionId);
  const result = useResult(sessionId);
  const [lang, setLang] = useState<Language>("python");
  const [source, setSource] = useState("");
  const [run, setRun] = useState<RunOut | null>(null);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const started = useRef<number | null>(null);
  const autoSubmitted = useRef(false);
  const submitted = result.data?.status === "judging" || result.data?.status === "done" || problem.data?.submitted === true;

  // 언어를 바꾸면 그 언어의 임시 저장본(없으면 시작 템플릿)을 연다
  const starter = useMemo(() => problem.data?.languages.find((l) => l.id === lang)?.starter ?? "", [problem.data, lang]);
  useEffect(() => { if (problem.data) setSource(loadDraft(sessionId, lang) ?? starter); }, [problem.data, lang, sessionId, starter]);
  // 자동 저장: 로컬 디바운스 2초 → sessionStorage
  useEffect(() => {
    if (!problem.data || submitted) return;
    const t = setTimeout(() => saveDraft(sessionId, lang, source), 2000);
    return () => clearTimeout(t);
  }, [source, lang, sessionId, problem.data, submitted]);

  // 시작 시각의 기준은 서버가 센 경과 시간(새로고침·다른 기기에서도 같다). 없으면 처음 문제를 받은 시각을 sessionStorage 에 기록해 쓴다.
  useEffect(() => {
    if (!problem.data || started.current !== null) return;
    started.current = problem.data.elapsed_sec != null ? Date.now() - problem.data.elapsed_sec * 1000 : codingStartedAt(sessionId);
  }, [problem.data, sessionId]);
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  const left = started.current !== null ? remainingMs(started.current, problem.data?.time_limit_sec, now) : null;

  const doRun = useCallback(async () => {
    setRunning(true);
    try { setRun(await runSamples(sessionId, lang, source)); } catch (e) {
      if (e instanceof ApiError && e.code === "RUN_IN_PROGRESS") toast.warning("이전 실행이 끝나면 다시 실행할 수 있어요");
      else if (e instanceof ApiError && e.code === "CODING_TIME_UP") toast.error("제한시간이 끝났어요. 더 이상 실행할 수 없습니다.", { code: e.code });
      else if (e instanceof ApiError && e.status === 429) toast.warning("실행 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.", e.code);
      else toast.error(e instanceof ApiError ? e.message : "실행에 실패했어요. 다시 시도해 주세요.", e instanceof ApiError ? { code: e.code, requestId: e.requestId } : undefined);
    } finally { setRunning(false); }
  }, [sessionId, lang, source]);

  const doSubmit = useCallback(async () => {
    setSubmitting(true);
    try {
      await submitCode(sessionId, lang, source);
      saveDraft(sessionId, lang, source);
      await qc.invalidateQueries({ queryKey: codeKeys.result(sessionId) });
    } catch (e) {
      if (e instanceof ApiError && e.code === "CODE_ALREADY_SUBMITTED") await qc.invalidateQueries({ queryKey: codeKeys.result(sessionId) });
      else if (e instanceof ApiError && e.code === "CODING_TIME_UP") toast.error("제한시간이 끝나 제출할 수 없어요. 코딩테스트를 종료해 주세요.", { code: e.code });
      else toast.error(e instanceof ApiError ? e.message : "제출에 실패했어요. 내용은 유지됩니다. 다시 시도해 주세요.", e instanceof ApiError ? { code: e.code, requestId: e.requestId } : undefined);
    } finally { setSubmitting(false); setConfirm(false); }
  }, [sessionId, lang, source, qc]);

  // 시간 종료 → 현재 코드를 자동 제출 (UI_SPEC §4.7)
  useEffect(() => {
    if (left === 0 && !submitted && !autoSubmitted.current && problem.data && source.trim()) { autoSubmitted.current = true; toast.warning("제한시간이 끝나 현재 코드를 제출했어요"); void doSubmit(); }
  }, [left, submitted, problem.data, source, doSubmit]);

  if (problem.isError) {
    const e = problem.error;
    const msg = e instanceof ApiError && e.code === "SANDBOX_DISABLED" ? "코딩테스트 실행 환경이 비활성화되어 있어요. 담당자에게 문의하세요." : e instanceof ApiError ? e.message : "문제를 불러오지 못했어요";
    return <Card className="mx-auto mt-10 max-w-lg"><ErrorState message={msg} onRetry={() => void problem.refetch()} /><div className="pb-6 text-center"><Button variant="secondary" onClick={onFinish} loading={finishing}>면접 종료하고 대기 화면으로</Button></div></Card>;
  }
  if (!problem.data) return <div className="mx-auto max-w-[1120px] space-y-3 p-4" aria-busy><Skeleton className="h-10 w-80" /><Skeleton className="h-96 w-full" /></div>;
  const p = problem.data;
  const timeUp = left === 0;

  return (
    <div className="mx-auto max-w-[1280px] space-y-3 px-4 py-4" data-testid="coding-pane">
      <div role="tablist" aria-label="면접 탭" className="flex items-center gap-2 border-b border-border">
        <button role="tab" aria-selected={false} disabled className="inline-flex items-center gap-1 px-4 py-2 text-sm text-muted"><Mic className="h-4 w-4" aria-hidden />음성 면접 ✓완료</button>
        <button role="tab" aria-selected className="border-b-2 border-primary px-4 py-2 text-sm font-semibold">{"</>"} 코딩테스트 ●</button>
        <span className={cn("ml-auto text-sm tabular-nums", left !== null && left < 60_000 && "font-semibold text-danger")} data-testid="coding-timer" aria-label="남은 시간">{left === null ? "" : `남은 시간 ${formatClock(left)}`}</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(280px,380px)_1fr]">
        <Card className="space-y-3 p-4 text-sm" aria-label="문제">
          <h1 className="text-lg font-bold" data-testid="problem-title">{p.title}</h1>
          <p className="whitespace-pre-line">{p.statement}</p>
          <section><h2 className="font-semibold">입력</h2><p className="whitespace-pre-line text-muted">{p.input_format}</p></section>
          <section><h2 className="font-semibold">출력</h2><p className="whitespace-pre-line text-muted">{p.output_format}</p></section>
          <section><h2 className="font-semibold">제약 조건</h2><ul className="list-disc pl-5 text-muted">{p.constraints.map((c) => <li key={c}>{c}</li>)}</ul></section>
          {p.examples.map((e, i) => (
            <section key={i}><h2 className="font-semibold">예시 {i + 1}</h2>
              <pre className="overflow-x-auto rounded bg-surface-2 p-2 text-xs">{`입력\n${e.input}출력\n${e.output}`}</pre></section>
          ))}
          <p className="text-xs text-muted">※ 실행 제한: {p.exec_time_limit_sec}초 · 메모리 {p.memory_limit_mb}MB · 네트워크 없음</p>
        </Card>

        <div className="space-y-3">
          <Card className="space-y-2 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-sm">언어
                <select value={lang} onChange={(e) => { saveDraft(sessionId, lang, source); setLang(e.target.value as Language); setRun(null); }} disabled={submitted}
                  className="h-9 rounded border border-border bg-surface px-2" aria-label="언어 선택" data-testid="lang-select">
                  {p.languages.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                </select></label>
              <div className="ml-auto flex gap-2">
                <Button variant="secondary" onClick={() => void doRun()} disabled={running || submitted || timeUp || !source.trim()} loading={running} data-testid="run-btn"><Play className="h-4 w-4" aria-hidden />실행</Button>
                <Button onClick={() => setConfirm(true)} disabled={submitting || submitted || timeUp || !source.trim()} data-testid="submit-btn"><Send className="h-4 w-4" aria-hidden />{submitted ? "제출 완료" : "제출"}</Button>
              </div>
            </div>
            <div className="h-[380px] overflow-hidden rounded border border-border" data-testid="editor">
              <MonacoEditor value={source} language={MONACO_LANG[lang]} onChange={setSource} readOnly={submitted} />
            </div>
            <p className="text-xs text-muted">ⓘ 케이스 수에 비례해 채점 시간이 걸립니다 (케이스당 약 1초). 제출은 한 번만 할 수 있어요.</p>
          </Card>

          <ResultPanel run={run} running={running} result={result.data} judging={result.data?.status === "judging" || submitting} onRefresh={() => void result.refetch()} />
          <FollowupChat onText={onText} />

          <div className="flex justify-end"><Button variant="secondary" onClick={() => { if (!submitted && !window.confirm("코드를 제출하지 않고 종료할까요? 코딩테스트는 평가에 반영되지 않습니다.")) return; onFinish(); }}
            loading={finishing} data-testid="finish-coding">코딩테스트 종료</Button></div>
        </div>
      </div>

      {confirm && (
        <div role="dialog" aria-modal="true" aria-label="제출 확인" className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm space-y-3 rounded-lg bg-surface p-5 shadow-xl">
            <h2 className="font-bold">코드를 제출할까요?</h2>
            <p className="text-sm text-muted">제출하면 수정할 수 없고, 제출한 코드에 대한 질문이 이어질 수 있어요.</p>
            <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setConfirm(false)} disabled={submitting}>취소</Button><Button onClick={() => void doSubmit()} loading={submitting} data-testid="submit-confirm">제출하기</Button></div>
          </div>
        </div>
      )}
    </div>
  );
}

function CaseRow({ c }: { c: CaseOut }) {
  return (
    <li className="rounded border border-border p-2 text-sm" data-testid="case-row">
      <div className="flex items-center gap-2">
        <span>케이스{c.index}</span><Badge tone={verdictTone(c.verdict)}>{c.verdict} {VERDICT_LABEL[c.verdict]}</Badge>
        <span className="text-xs tabular-nums text-muted">{(c.runtime_ms / 1000).toFixed(2)}s</span>
        {!c.visible && <span className="inline-flex items-center gap-1 text-xs text-muted"><Lock className="h-3 w-3" aria-hidden />비공개</span>}
      </div>
      {c.visible && c.stdout && <pre className="mt-1 max-h-24 overflow-auto rounded bg-surface-2 p-1 text-xs">{c.stdout}</pre>}
      {c.stderr && <pre className="mt-1 max-h-24 overflow-auto rounded bg-danger-bg p-1 text-xs text-danger">{c.stderr}</pre>}
      {c.truncated && <p className="text-xs text-muted">출력이 64KB 에서 잘렸어요.</p>}
    </li>
  );
}

function ResultPanel({ run, running, result, judging, onRefresh }: { run: RunOut | null; running: boolean; result: ReturnType<typeof useResult>["data"]; judging: boolean; onRefresh: () => void }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => { setSlow(false); if (!judging) return; const t = setTimeout(() => setSlow(true), 30_000); return () => clearTimeout(t); }, [judging]);
  const done = result?.status === "done" ? result : null;
  return (
    <Card className="space-y-2 p-3" aria-live="polite" aria-label="실행 결과" data-testid="result-panel">
      <h2 className="font-semibold">실행 결과</h2>
      {running && <p className="flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />샘플 케이스를 실행하고 있어요…</p>}
      {judging && !done && (
        <p className="flex items-center gap-2 text-sm" data-testid="judging"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />채점 중입니다…
          {slow && <Button variant="secondary" onClick={onRefresh}>상태 새로고침</Button>}</p>
      )}
      {done ? (
        <div className="space-y-2" data-testid="final-result">
          <p className="flex items-center gap-2 text-sm font-semibold">최종 판정 <Badge tone={verdictTone(done.verdict ?? "")} data-testid="final-verdict">{done.verdict} {VERDICT_LABEL[done.verdict ?? ""]}</Badge></p>
          {done.compile_log && <pre className="max-h-32 overflow-auto rounded bg-danger-bg p-2 text-xs text-danger">{done.compile_log}</pre>}
          <ul className="space-y-1">{done.cases.map((c) => <CaseRow key={c.index} c={c} />)}</ul>
        </div>
      ) : run && !running ? (
        <div className="space-y-2" data-testid="run-result">
          <p className="text-sm">샘플 실행 결과 <Badge tone={verdictTone(run.verdict)}>{run.verdict} {VERDICT_LABEL[run.verdict]}</Badge></p>
          {run.compile_log && <pre className="max-h-32 overflow-auto rounded bg-danger-bg p-2 text-xs text-danger">{run.compile_log}</pre>}
          <ul className="space-y-1">{run.cases.map((c) => <CaseRow key={c.index} c={c} />)}</ul>
        </div>
      ) : !running && !judging && <p className="text-sm text-muted">[실행] 으로 샘플 케이스를 먼저 확인해 보세요.</p>}
    </Card>
  );
}

/** 코드 꼬리질문 채팅 (TRD §5.6, §7.7): 질문 수신 → 텍스트 입력(최대 2,000자) → text_answer. 시간 초과는 서버가 빈 답변으로 처리한다. */
function FollowupChat({ onText }: { onText: (turnId: string, text: string) => boolean }) {
  const chat = useInterviewStore((s) => s.codeChat);
  const q = useInterviewStore((s) => s.codeQuestion);
  const [text, setText] = useState("");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { if (!q) return; setText(""); const id = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(id); }, [q]);
  if (chat.length === 0 && !q) return null;
  const left = q ? Math.max(0, Math.ceil((q.deadline - now) / 1000)) : 0;
  const send = () => {
    if (!q || !text.trim()) return;
    if (onText(q.turnId, text.trim())) useInterviewStore.getState().answerCode(q.turnId, text.trim());
    else toast.error("연결이 끊겨 답변을 보내지 못했어요. 잠시 후 다시 시도해 주세요.");
  };
  return (
    <Card className="space-y-2 p-3" aria-label="코드 꼬리질문" data-testid="followup-chat">
      <h2 className="font-semibold">제출한 코드에 대한 질문</h2>
      <ol className="space-y-2">
        {chat.map((c, i) => <li key={`${c.turnId}-${c.role}-${i}`} className={cn("max-w-[85%] rounded-lg p-2 text-sm", c.role === "ai" ? "bg-surface-2" : "ml-auto bg-primary/10")} data-role={c.role}>{c.text}</li>)}
      </ol>
      {q && (
        <div className="space-y-1">
          <textarea aria-label="답변 입력" className="h-24 w-full rounded border border-border bg-surface p-2 text-sm" value={text} maxLength={MAX_FOLLOWUP_CHARS} onChange={(e) => setText(e.target.value)} data-testid="followup-input" />
          <div className="flex items-center justify-between text-xs text-muted"><span className="tabular-nums">{text.length}/{MAX_FOLLOWUP_CHARS} · 남은 시간 {left}초 (초과 시 빈 답변 처리)</span>
            <Button onClick={send} disabled={!text.trim()} data-testid="followup-send">답변 보내기</Button></div>
        </div>
      )}
    </Card>
  );
}
