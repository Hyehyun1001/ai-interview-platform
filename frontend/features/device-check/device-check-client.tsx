"use client";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Circle, CircleDot, HelpCircle, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { ApplyStepper } from "@/components/ui/stepper";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { MY_APPS_KEY, createSession, saveDeviceCheck, startSession, useMyApplications } from "@/features/applicant/api";
import { CameraCheck } from "./camera-check";
import { DeviceSelect } from "./device-select";
import { MicCheck } from "./mic-check";
import { SpeakerCheck } from "./speaker-check";
import { StartingOverlay, type StartPhase } from "./starting-overlay";
import { STEPS, STEP_LABEL, START_TIMEOUT_MS, activeStep, allPassed, initialStates, isUnlocked, readDeviceChoice, resetFrom, saveDeviceChoice, type Step, type StepStates, type StepStatus } from "./device-logic";
import { useDeviceList } from "./use-device-list";

const ICON: Record<StepStatus, typeof Circle> = { idle: Circle, checking: CircleDot, pass: CheckCircle2, fail: XCircle };

const sleep = (ms: number, signal: AbortSignal) => new Promise<void>((res) => {
  const t = setTimeout(res, ms);
  signal.addEventListener("abort", () => { clearTimeout(t); res(); }, { once: true });
});

/** APP-06 사전 환경 점검 (UI_SPEC §4.5). 카메라 → 마이크 → 스피커 순서가 고정이며, 모두 통과해 서버에 저장된 뒤에만 [면접 시작]이 켜진다. */
export function DeviceCheckClient({ applicationId }: { applicationId: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const apps = useMyApplications();
  const app = apps.data?.find((a) => a.application_id === applicationId);
  const { lists, refresh } = useDeviceList();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionErr, setSessionErr] = useState<string | null>(null);
  const [states, setStates] = useState<StepStates>(initialStates);
  const [keys, setKeys] = useState<Record<Step, number>>({ camera: 0, mic: 0, speaker: 0 });
  const [chosen, setChosen] = useState(readDeviceChoice);       // 사용자가 고른 장치 → 스트림 요청에 쓰인다
  const [actual, setActual] = useState<{ video?: string; audio?: string }>({});  // 실제로 열린 장치 → 선택 상자 표시용
  const [saved, setSaved] = useState<"idle" | "saving" | "ok" | "error">("idle");
  const [phase, setPhase] = useState<StartPhase | null>(null);
  const abort = useRef<AbortController | null>(null);
  const degradedOk = useRef(false);  // 경량 모드 고지를 보고 "그대로 진행"을 고른 뒤에만 true
  const secure = typeof window === "undefined" || window.isSecureContext;
  const canSink = typeof HTMLMediaElement !== "undefined" && "setSinkId" in HTMLMediaElement.prototype;

  // 세션 확보 (멱등: 이미 있으면 같은 세션을 돌려준다). 동의/이력서 단계가 빠졌으면 이력서 단계로 되돌린다.
  const sessionRequested = useRef(false);
  useEffect(() => {
    if (!app || sessionRequested.current) return;
    sessionRequested.current = true;
    createSession(applicationId).then((s) => setSessionId(s.session_id)).catch((e: unknown) => {
      if (e instanceof ApiError && e.status === 409) {
        toast.warning("이력서 제출을 먼저 완료해 주세요", e.code);
        router.replace(`/apply/${applicationId}/resume`);
      } else setSessionErr(e instanceof ApiError ? e.message : "면접을 준비하지 못했어요");
    });
  }, [app, applicationId, router]);

  useEffect(() => { saveDeviceChoice(chosen); }, [chosen]);
  useEffect(() => () => abort.current?.abort(), []);

  const pass = useCallback((step: Step) => setStates((s) => (s[step] === "pass" ? s : { ...s, [step]: "pass" })), []);
  const recheck = (step: Step) => {
    setStates((s) => resetFrom(s, step));
    setKeys((k) => ({ ...k, ...Object.fromEntries(STEPS.slice(STEPS.indexOf(step)).map((x) => [x, k[x] + 1])) }));
    setSaved("idle");
  };

  // 3단계 모두 통과 → 서버에 저장 (영상·음성 원본이나 장치 이름은 보내지 않는다)
  useEffect(() => {
    if (!sessionId || !allPassed(states) || saved !== "idle") return;
    setSaved("saving");
    saveDeviceCheck(sessionId).then(() => setSaved("ok")).catch(() => { setSaved("error"); toast.error("점검 결과를 저장하지 못했어요. 다시 시도해 주세요."); });
  }, [sessionId, states, saved]);

  const start = useCallback(async () => {
    if (!sessionId) return;
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    const deadline = Date.now() + START_TIMEOUT_MS;
    let resaved = false;
    setPhase({ kind: "starting", stage: "preparing" });
    while (!ctl.signal.aborted) {
      try {
        const r = await startSession(sessionId);  // 202 면 같은 호출을 반복해 준비 단계를 따라간다
        if (ctl.signal.aborted) return;
        if (r.status === "ready") {
          if (r.degraded_mode && !degradedOk.current) { setPhase({ kind: "degraded" }); return; }
          void qc.invalidateQueries({ queryKey: MY_APPS_KEY });
          router.push(`/interview/${sessionId}`);
          return;
        }
        setPhase({ kind: "starting", stage: r.status });
      } catch (e) {
        if (ctl.signal.aborted) return;
        if (e instanceof ApiError && e.code === "SESSION_SLOT_UNAVAILABLE") {
          const wait = Number(e.details["retry_after_sec"] ?? 30);
          for (let left = wait; left > 0 && !ctl.signal.aborted; left--) { setPhase({ kind: "queued", retryInSec: left }); await sleep(1000, ctl.signal); }
          if (ctl.signal.aborted) return;
          setPhase({ kind: "starting", stage: "preparing" });
          continue;
        }
        if (e instanceof ApiError && e.code === "DEVICE_CHECK_REQUIRED" && !resaved) {  // 서버에 저장이 안 된 상태 → 한 번만 다시 저장하고 재시도
          resaved = true;
          await saveDeviceCheck(sessionId).catch(() => undefined);
          continue;
        }
        toast.error(e instanceof ApiError ? e.message : "면접을 시작하지 못했어요", { code: e instanceof ApiError ? e.code : undefined });
        setPhase(null);
        return;
      }
      if (Date.now() > deadline) { setPhase({ kind: "timeout" }); return; }
      await sleep(1000, ctl.signal);
    }
  }, [sessionId, qc, router]);

  const onProceed = () => { degradedOk.current = true; void start(); };

  if (!secure) return <Card className="mx-auto max-w-lg"><ErrorState message="보안 연결(HTTPS)에서만 장치를 점검할 수 있어요. 관리자에게 문의해 주세요." /></Card>;
  if (apps.isError || (apps.data && !app)) return <Card className="mx-auto max-w-lg"><ErrorState message="지원 내역을 찾을 수 없어요" /><div className="pb-6 text-center"><Link href="/jobs" className="text-primary">공고 목록으로</Link></div></Card>;
  if (sessionErr) return <Card className="mx-auto max-w-lg"><ErrorState message={sessionErr} onRetry={() => { sessionRequested.current = false; setSessionErr(null); void apps.refetch(); }} /></Card>;
  if (!app || !sessionId) return <div className="space-y-3" aria-busy><Skeleton className="h-8 w-80" /><Skeleton className="h-72 w-full" /></div>;

  const current = activeStep(states);
  const ready = allPassed(states) && saved === "ok";
  const unlocked = (s: Step) => isUnlocked(states, s);

  return (
    <div className="space-y-6">
      <ApplyStepper current={3} />
      <ol aria-label="점검 단계" className="flex flex-wrap gap-3">
        {STEPS.map((s, i) => {
          const st = states[s] === "idle" && current === s ? "checking" : states[s];
          const Icon = ICON[st];
          return (
            <li key={s} aria-current={current === s ? "step" : undefined} data-testid={`step-${s}`} data-status={st}>
              <button type="button" disabled={states[s] !== "pass"} onClick={() => recheck(s)} title={states[s] === "pass" ? "다시 점검" : undefined}
                className={cn("inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm", st === "pass" ? "border-success text-success" : current === s ? "border-primary font-bold" : "border-border text-muted")}>
                <Icon className="h-4 w-4" aria-hidden />{i + 1}. {STEP_LABEL[s]}{st === "pass" ? " 통과" : current === s ? " 진행 중" : ""}
              </button>
            </li>
          );
        })}
      </ol>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3 p-4">
          <h2 className="font-bold">카메라 점검</h2>
          <CameraCheck key={keys.camera} sessionId={sessionId} deviceId={chosen.video}
            onPass={() => pass("camera")} onActualDevice={(id) => { setActual((a) => ({ ...a, video: id })); void refresh(); }} onStreamOpened={() => undefined} />
          <DeviceSelect label="카메라" devices={lists.video} value={chosen.video ?? actual.video}
            onChange={(id) => { setChosen((c) => ({ ...c, video: id })); recheck("camera"); }} />
        </Card>

        <Card className="space-y-5 p-4">
          <section className="space-y-3" aria-labelledby="mic-h">
            <h2 id="mic-h" className="font-bold">마이크 점검</h2>
            <DeviceSelect label="입력 장치" devices={lists.audio} value={chosen.audio ?? actual.audio}
              onChange={(id) => { setChosen((c) => ({ ...c, audio: id })); recheck("mic"); }} disabled={!unlocked("mic")} />
            <MicCheck key={keys.mic} deviceId={chosen.audio} active={unlocked("mic")} passed={states.mic === "pass"}
              onPass={() => pass("mic")} onActualDevice={(id) => { setActual((a) => ({ ...a, audio: id })); void refresh(); }} onStreamOpened={() => undefined} />
          </section>
          <section className="space-y-3 border-t border-border pt-4" aria-labelledby="spk-h">
            <h2 id="spk-h" className="font-bold">스피커 점검</h2>
            {canSink && <DeviceSelect label="출력 장치" devices={lists.output} value={chosen.output} onChange={(id) => setChosen((c) => ({ ...c, output: id }))} disabled={!unlocked("speaker")} />}
            <SpeakerCheck key={keys.speaker} outputId={chosen.output} active={unlocked("speaker")} passed={states.speaker === "pass"} onPass={() => pass("speaker")} />
          </section>
        </Card>
      </div>

      <details className="rounded border border-border p-3 text-sm">
        <summary className="flex cursor-pointer items-center gap-1 font-medium"><HelpCircle className="h-4 w-4" aria-hidden />문제 해결 가이드</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
          <li>권한 안내가 뜨면 [허용]을 눌러 주세요. 거부했다면 주소창 왼쪽 아이콘에서 카메라·마이크를 허용한 뒤 새로고침합니다.</li>
          <li>다른 화상회의·녹음 앱이 카메라나 마이크를 쓰고 있다면 종료해 주세요.</li>
          <li>소리가 작다면 시스템 입력 볼륨과 마이크 음소거 여부를 확인해 주세요.</li>
          <li>면접은 데스크톱 최신 Chrome/Edge 에서 응시해 주세요.</li>
        </ul>
      </details>

      <footer className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/jobs/${app.job.id}`} className="inline-flex items-center gap-1 text-sm text-muted hover:text-text"><ArrowLeft className="h-4 w-4" aria-hidden />이전: 공고 상세</Link>
        <div className="flex items-center gap-3">
          {saved === "error" && <Button variant="secondary" onClick={() => setSaved("idle")}>점검 결과 다시 저장</Button>}
          <Button onClick={() => { degradedOk.current = false; void start(); }} disabled={!ready || !!phase} data-testid="start-interview">면접 시작 ›</Button>
        </div>
      </footer>
      {!ready && <p className="text-right text-xs text-muted">카메라·마이크·스피커 3개를 모두 통과해야 면접을 시작할 수 있어요.</p>}

      {phase && <StartingOverlay phase={phase} onRetry={() => { degradedOk.current = false; void start(); }} onCancel={() => { abort.current?.abort(); setPhase(null); }} onProceed={onProceed} />}
    </div>
  );
}
