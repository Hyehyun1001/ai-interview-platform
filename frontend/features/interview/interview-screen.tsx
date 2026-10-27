"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { CodingPane } from "@/features/coding/coding-pane";
import { AnswerDoneButton, CountdownOverlay, FailureScreen, ReconnectOverlay, StartGate, ThinkingIndicator } from "./components/overlays";
import { AnswerTimer, GazeWarningBanner, InterviewProgressBar, InterviewerPanel, MicLevelMeter, NoticeBanner, WebcamOverlay, useRemainingMs } from "./components/primitives";
import { readGazeBase } from "@/features/device-check/device-logic";
import { MAX_RECONNECT } from "./protocol";
import { useInterviewStore } from "./store";
import { useGazeTracker } from "./use-gaze-tracker";
import { useInterviewSocket } from "./use-interview-socket";
import { useMediaCapture } from "./use-media-capture";

const MIN_ANSWER_MS = 1000;  // 답변 시작 후 1초 이내에는 [답변 완료]를 비활성 (오조작 방지)

/** APP-07 실시간 면접 화면 (UI_SPEC §4.6). 상태는 서버가 결정하고 이 컴포넌트는 스토어를 렌더링한다. */
export function InterviewScreen({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const s = useInterviewStore();
  const media = useMediaCapture();
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [mediaErr, setMediaErr] = useState<ReturnType<typeof useMediaCapture>["error"]>(null);
  const answerStartedAt = useRef(0);
  const thinkingSince = useRef(Date.now());
  const [, force] = useState(0);

  const onUnauthorized = useCallback(() => router.replace(`/login?next=${encodeURIComponent(`/interview/${sessionId}`)}`), [router, sessionId]);
  const sock = useInterviewSocket(sessionId, onUnauthorized, media.onAck);

  useEffect(() => { useInterviewStore.getState().reset(); return () => useInterviewStore.getState().reset(); }, [sessionId]);

  // 미디어 채널은 control 채널이 연결된 뒤에 연다 (서버는 control 이 먼저 있어야 media 를 받는다)
  useEffect(() => {
    if (sock.controlOpen && sock.mediaToken && media.status === "ready") media.connect(sessionId, sock.mediaToken, sock.refreshMediaToken);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sock.controlOpen, sock.mediaToken, media.status]);

  // 오디오는 답변 중에만 전송
  useEffect(() => {
    media.setSending(s.phase === "answering");
    if (s.phase === "answering") answerStartedAt.current = Date.now();
    if (s.phase === "thinking") thinkingSince.current = Date.now();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.phase]);

  useGazeTracker({
    video, enabled: media.status === "ready" && s.phase !== "gate" && s.phase !== "finished", active: s.phase === "answering",
    onEvent: sock.sendGaze, initialBase: readGazeBase(sessionId),  // APP-06 에서 정면 보정을 마쳤다면 그 값으로 바로 시작
  });

  // 면접 종료 → 리포트 생성 시작(best-effort) 후 대기 화면
  useEffect(() => {
    if (s.phase !== "finished") return;
    media.stop();
    if (s.finishedNext === "done") {
      void apiFetch(`/api/v1/sessions/${sessionId}/finish`, { method: "POST" }).catch(() => undefined);
      router.replace(`/interview/${sessionId}/waiting`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.phase]);

  // 진행 중 이탈 경고
  useEffect(() => {
    const live = !["gate", "failed", "blocked", "finished"].includes(s.phase);
    if (!live) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [s.phase]);

  // 답변 완료 버튼 활성화 시점 갱신
  useEffect(() => {
    if (s.phase !== "answering") return;
    const id = setTimeout(() => force((n) => n + 1), MIN_ANSWER_MS + 50);
    return () => clearTimeout(id);
  }, [s.phase]);

  const remaining = useRemainingMs(s.phase === "answering" ? s.answerDeadline : null);

  const [finishing, setFinishing] = useState(false);
  async function finishCoding() {
    setFinishing(true);
    try {
      await apiFetch(`/api/v1/sessions/${sessionId}/finish`, { method: "POST" });
      media.stop();
      router.replace(`/interview/${sessionId}/waiting`);
    } catch { toast.error("종료 처리에 실패했어요. 다시 시도해 주세요."); setFinishing(false); }
  }

  const start = async () => {
    setBusy(true);
    const err = await media.acquire();
    setMediaErr(err);
    setBusy(false);
    if (!err) void sock.begin();
  };

  if (s.phase === "gate") return <StartGate onStart={start} busy={busy} error={mediaErr} />;
  if (s.phase === "failed" || s.phase === "blocked") {
    return <FailureScreen state={s} onRetry={() => void sock.retry()} onExit={() => router.replace("/jobs")} />;
  }
  if (s.codingActive) {  // 질문이 모두 끝나 코딩테스트 탭으로 전환 (UI_SPEC §4.7)
    return (
      <>
        <CodingPane sessionId={sessionId} finishing={finishing} onText={(turnId, text) => sock.send({ type: "text_answer", turn_id: turnId, text })} onFinish={() => void finishCoding()} />
        {s.phase === "reconnecting" && <ReconnectOverlay attempt={s.reconnectAttempt} max={MAX_RECONNECT} />}
      </>
    );
  }

  const q = s.question;
  const answering = s.phase === "answering";
  const canFinish = answering && Date.now() - answerStartedAt.current >= MIN_ANSWER_MS;
  const followup = q && q.kind !== "main" ? "꼬리질문" : undefined;

  return (
    <div className="mx-auto max-w-[1120px] space-y-4 px-4 py-4">
      <InterviewProgressBar main={q?.mainIndex ?? 0} total={s.totalMain || q?.mainTotal || 0} followupLabel={followup} codingEnabled={s.codingEnabled} />
      <GazeWarningBanner gaze={s.gaze} />
      {s.degraded && <NoticeBanner tone="warning">{s.degraded}</NoticeBanner>}
      {s.notice && <NoticeBanner tone="info">{s.notice}</NoticeBanner>}
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <InterviewerPanel text={q?.text ?? null} kind={q?.kind} speaking={s.ttsPlaying} captionOnly={s.captionOnly} />
        <div className="space-y-4">
          <WebcamOverlay stream={media.stream} onVideo={setVideo} gazeStatus={s.gazeStatus} recording={answering} />
          <MicLevelMeter level={s.micLevel} listening={answering} />
          <AnswerTimer remainingMs={remaining} totalSec={q?.timeLimitSec ?? s.answerLimitSec} />
          {answering && s.liveTranscript && <p className="rounded bg-surface-2 p-3 text-xs text-muted" data-testid="live-transcript">{s.liveTranscript}</p>}
          {s.phase === "thinking" && <ThinkingIndicator stage={s.thinkingStage} since={thinkingSince.current} />}
          <AnswerDoneButton enabled={canFinish} onClick={() => sock.sendAnswerEnd("user")} />
        </div>
      </div>
      <CountdownOverlay n={s.phase === "countdown" ? s.countdown : null} />
      {s.phase === "reconnecting" && <ReconnectOverlay attempt={s.reconnectAttempt} max={MAX_RECONNECT} />}
    </div>
  );
}
