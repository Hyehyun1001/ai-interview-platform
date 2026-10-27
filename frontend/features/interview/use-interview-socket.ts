"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiFetch } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import type { components } from "@/types/api";
import { CLOSE, MAX_RECONNECT, backoffMs, parseServerMessage, wsBase, type ClientMessage, type GazeKind, type ServerMessage } from "./protocol";
import { readDeviceChoice } from "@/features/device-check/device-logic";
import { useInterviewStore } from "./store";

export type WsTokens = components["schemas"]["WsTokenResponse"];

const ANSWER_END_DEBOUNCE_MS = 2000;
const CONFLICT_RETRIES = 3;       // ALREADY_CONNECTED: 새로고침/StrictMode 직후 서버가 이전 연결을 정리하기 전의 경합을 흡수
const CONFLICT_RETRY_MS = 600;
const SLOT_RETRY_MS = 30_000;     // 동시 면접 한도 초과: 대기 안내 후 30초마다 재시도 (TRD §11 #14)
const ANSWER_START_DELAY_MS = 1000;  // 카운트다운 n=1 을 보여준 뒤 answer_start (UI_SPEC §4.6.4)

export const fetchWsTokens = (sessionId: string) => apiFetch<WsTokens>(`/api/v1/sessions/${sessionId}/ws-token`, { method: "POST" });

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/**
 * 제어 채널(WS /ws/sessions/{id}/control) 연결·재접속·메시지 처리·TTS 재생.
 * 서버 메시지는 스토어 리듀서가 상태로 옮기고(store.ts), 이 훅은 부수효과(전송·재생·타이머·재접속)만 맡는다.
 */
export function useInterviewSocket(sessionId: string, onUnauthorized: () => void, onAck?: (ackSeq: number) => void) {
  const apply = useInterviewStore((s) => s.apply);
  const [mediaToken, setMediaToken] = useState<string | null>(null);
  const [controlOpen, setControlOpen] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const closing = useRef(false);               // 우리가 의도적으로 닫는 중 (재접속 금지)
  const attempt = useRef(0);
  const conflicts = useRef(0);
  const lastError = useRef<string | null>(null);  // 닫히기 직전 서버가 보낸 비복구 에러 코드 (4409 구분용)
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  const ttsChunks = useRef(new Map<string, Uint8Array[]>());
  const audioRef = useRef<{ el: HTMLAudioElement; url: string } | null>(null);
  const lastEndAt = useRef(0);
  const connectRef = useRef<() => Promise<void>>(async () => {});
  const onAckRef = useRef(onAck);
  onAckRef.current = onAck;

  const later = useCallback((fn: () => void, ms: number) => {
    const t = setTimeout(() => { timers.current.delete(t); fn(); }, ms);
    timers.current.add(t);
    return t;
  }, []);

  const send = useCallback((msg: ClientMessage): boolean => {
    const ws = wsRef.current;
    if (ws?.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(msg));
    return true;
  }, []);

  // ── TTS 재생 ───────────────────────────────────────────────────────────────
  const stopTts = useCallback(() => {
    const cur = audioRef.current;
    if (!cur) return;
    audioRef.current = null;
    cur.el.pause();
    URL.revokeObjectURL(cur.url);
    useInterviewStore.getState().patch({ ttsPlaying: false });
  }, []);

  const playTts = useCallback((turnId: string, parts: Uint8Array[], format: string) => {
    const blob = new Blob(parts as BlobPart[], { type: format === "mp3" ? "audio/mpeg" : "audio/wav" });
    const url = URL.createObjectURL(blob);
    const el = new Audio(url);
    const out = readDeviceChoice().output;  // 사전 점검에서 고른 출력 장치 (setSinkId 지원 브라우저만)
    if (out && "setSinkId" in el) void (el as HTMLAudioElement & { setSinkId(id: string): Promise<void> }).setSinkId(out).catch(() => undefined);
    const entry = { el, url };
    audioRef.current = entry;
    let sent = false;
    const finish = (ok: boolean) => {
      if (sent) return;
      sent = true;
      if (audioRef.current === entry) audioRef.current = null;
      URL.revokeObjectURL(url);
      const st = useInterviewStore.getState();
      st.patch({ ttsPlaying: false, ...(ok ? {} : { captionOnly: true }) });
      // 재생이 끝났거나(또는 불가능해) 낭독이 끝난 것으로 보고 서버에 알린다 → 서버가 카운트다운을 시작
      if (st.question?.turnId === turnId) send({ type: "tts_done", turn_id: turnId });
    };
    el.onended = () => finish(true);
    el.onerror = () => finish(false);
    useInterviewStore.getState().patch({ ttsPlaying: true });
    el.play().catch(() => finish(false));  // 자동재생 차단 등 → 자막만 표시하고 진행
  }, [send]);

  // ── 메시지 처리 ────────────────────────────────────────────────────────────
  const handleMessage = useCallback((m: ServerMessage) => {
    apply(m);
    const st = useInterviewStore.getState();
    switch (m.type) {
      case "ping": send({ type: "pong" }); break;  // 서버 keepalive: 3주기 무응답이면 4408 로 끊긴다
      case "question":
        stopTts();
        ttsChunks.current.clear();
        break;
      case "tts_chunk": {
        if (st.question?.turnId !== m.turn_id) break;  // 이미 다른 질문으로 넘어간 청크
        const parts = ttsChunks.current.get(m.turn_id) ?? [];
        parts[m.idx] = b64ToBytes(m.data_b64);
        ttsChunks.current.set(m.turn_id, parts);
        if (m.last) { ttsChunks.current.delete(m.turn_id); playTts(m.turn_id, parts.filter(Boolean), m.format); }
        break;
      }
      case "countdown":
        if (m.n === 1) {
          later(() => {
            const s = useInterviewStore.getState();
            if (s.phase === "countdown" && s.question?.turnId === m.turn_id) {
              send({ type: "answer_start", turn_id: m.turn_id });
              s.startAnswering(s.question.timeLimitSec);
            }
          }, ANSWER_START_DELAY_MS);
        }
        break;
      case "error":
        if (!m.recoverable) lastError.current = m.code;
        if (m.code === "TTS_FAILED") toast.warning(m.message, "TTS_FAILED");
        else if (m.code === "ANSWER_TOO_SHORT") toast.info(m.message);
        else if (m.code === "STT_FAILED") toast.warning(m.message, "STT_FAILED");
        break;
      case "degraded": toast.warning(m.message, "DEGRADED"); break;
      case "ack": onAckRef.current?.(m.ack_seq); break;  // 미디어 재전송 버퍼 정리
      default: break;
    }
  }, [apply, later, playTts, send, stopTts]);

  // ── 연결 / 재접속 ──────────────────────────────────────────────────────────
  const fail = useCallback((kind: "auth" | "forbidden" | "conflict" | "slot" | "inactive" | "network" | "protocol", message: string) => {
    useInterviewStore.getState().patch({ phase: kind === "conflict" || kind === "slot" || kind === "inactive" ? "blocked" : "failed", failure: { kind, message } });
  }, []);

  const scheduleReconnect = useCallback(() => {
    attempt.current += 1;
    const delay = backoffMs(attempt.current);
    if (delay === null) { fail("network", "연결할 수 없어요. 답변은 안전하게 저장되어 있습니다."); return; }
    useInterviewStore.getState().patch({ reconnectAttempt: attempt.current });
    later(() => void connectRef.current(), delay);
  }, [fail, later]);

  const handleClose = useCallback((code: number) => {
    setControlOpen(false);
    wsRef.current = null;
    stopTts();
    if (closing.current) return;
    const err = lastError.current;
    lastError.current = null;
    switch (code) {
      case CLOSE.UNAUTHORIZED: fail("auth", "로그인이 만료되었습니다."); onUnauthorized(); return;
      case CLOSE.FORBIDDEN: case CLOSE.NOT_FOUND: fail("forbidden", "이 면접에 접근할 수 없습니다."); return;
      case CLOSE.PROTOCOL: fail("protocol", "통신 규격 오류가 발생했습니다. 새로고침해 주세요."); return;
      case CLOSE.CONFLICT:
        if (err === "ALREADY_CONNECTED") {
          if (conflicts.current < CONFLICT_RETRIES) { conflicts.current += 1; later(() => void connectRef.current(), CONFLICT_RETRY_MS); }
          else fail("conflict", "다른 창에서 면접이 진행 중입니다.");
          return;
        }
        if (err === "SESSION_SLOT_UNAVAILABLE") { fail("slot", "현재 다른 지원자가 면접 중입니다. 잠시 후 자동으로 다시 시도합니다."); later(() => void connectRef.current(), SLOT_RETRY_MS); return; }
        if (err === "SESSION_NOT_ACTIVE") { fail("inactive", "이미 종료되었거나 만료된 면접입니다."); return; }
        break;  // CONTROL_REQUIRED 등은 재접속으로 해소
      default: break;
    }
    useInterviewStore.getState().connectionLost();
    scheduleReconnect();
  }, [fail, later, onUnauthorized, scheduleReconnect, stopTts]);

  const connect = useCallback(async () => {
    if (closing.current) return;
    const st = useInterviewStore.getState();
    // 처음 시작하거나 실패·대기 화면에서 다시 시도하면 "연결 중", 진행 중 끊겼다 돌아오는 경우는 "재연결 중"
    const fresh = st.phase === "gate" || st.phase === "blocked" || st.phase === "failed" || st.phase === "connecting";
    st.patch({ phase: fresh ? "connecting" : "reconnecting" });
    let tokens: WsTokens;
    try {
      tokens = await fetchWsTokens(sessionId);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 401) { fail("auth", "로그인이 만료되었습니다."); onUnauthorized(); return; }
        if (e.status === 404 || e.status === 403) { fail("forbidden", "이 면접에 접근할 수 없습니다."); return; }
        if (e.code === "SESSION_NOT_ACTIVE") { fail("inactive", "이미 종료되었거나 만료된 면접입니다."); return; }
        if (e.status < 500) { fail("protocol", e.message); return; }
      }
      scheduleReconnect();
      return;
    }
    if (closing.current) return;
    setMediaToken(tokens.media_token);
    const ws = new WebSocket(`${wsBase()}/ws/sessions/${sessionId}/control?token=${encodeURIComponent(tokens.control_token)}`);
    wsRef.current = ws;
    ws.onopen = () => setControlOpen(true);
    ws.onmessage = (ev) => {
      const m = parseServerMessage(ev.data);
      if (m) handleMessage(m);
    };
    ws.onclose = (ev) => handleClose(ev.code);
    ws.onerror = () => { /* 상세는 onclose 에서 처리 */ };
  }, [fail, handleClose, handleMessage, onUnauthorized, scheduleReconnect, sessionId]);
  connectRef.current = connect;

  /** 사용자 제스처(시작 버튼) 이후 호출한다. */
  const begin = useCallback(() => {
    closing.current = false;
    attempt.current = 0;
    conflicts.current = 0;
    return connect();
  }, [connect]);

  /** 실패 화면의 [다시 연결] */
  const retry = useCallback(() => {
    for (const t of timers.current) clearTimeout(t);
    timers.current.clear();
    attempt.current = 0;
    conflicts.current = 0;
    return connect();
  }, [connect]);

  /** 미디어 채널 재접속용 새 토큰 (토큰은 1회용이라 재사용할 수 없다) */
  const refreshMediaToken = useCallback(async (): Promise<string | null> => {
    try { return (await fetchWsTokens(sessionId)).media_token; } catch { return null; }
  }, [sessionId]);

  // ── 사용자 동작 ────────────────────────────────────────────────────────────
  const sendAnswerEnd = useCallback((reason: "user" | "timeout" = "user") => {
    const s = useInterviewStore.getState();
    if (s.phase !== "answering" || !s.question) return;
    const now = Date.now();
    if (reason === "user" && now - lastEndAt.current < ANSWER_END_DEBOUNCE_MS) return;  // 오조작 방지: 2초 이내 재클릭 무시
    lastEndAt.current = now;
    send({ type: "answer_end", turn_id: s.question.turnId, reason });
    s.patch({ phase: "thinking", thinkingStage: "stt", answerDeadline: null });
  }, [send]);

  const sendGaze = useCallback((e: { kind: GazeKind; start_ms: number; end_ms: number; yaw?: number; pitch?: number }) => {
    const turnId = useInterviewStore.getState().question?.turnId;
    if (turnId) send({ type: "gaze_event", turn_id: turnId, ...e });
  }, [send]);

  // 클라이언트 측 제한시간: 서버도 독자적으로 종료하지만 UI 가 먼저 thinking 으로 넘어가게 한다 (UI_SPEC §4.6.4)
  const deadline = useInterviewStore((s) => s.answerDeadline);
  const phase = useInterviewStore((s) => s.phase);
  useEffect(() => {
    if (phase !== "answering" || deadline === null) return;
    const t = setTimeout(() => sendAnswerEnd("timeout"), Math.max(0, deadline - Date.now()));
    return () => clearTimeout(t);
  }, [phase, deadline, sendAnswerEnd]);

  // 언마운트: 재접속을 막고 모든 자원 정리
  useEffect(() => {
    const pending = timers.current;
    return () => {
      closing.current = true;
      for (const t of pending) clearTimeout(t);
      pending.clear();
      stopTts();
      wsRef.current?.close(1000);
      wsRef.current = null;
    };
  }, [stopTts]);

  return { begin, retry, send, sendAnswerEnd, sendGaze, mediaToken, controlOpen, refreshMediaToken, maxReconnect: MAX_RECONNECT };
}
