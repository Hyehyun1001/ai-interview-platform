import { create } from "zustand";
import type { ServerMessage, ThinkingStage, TurnKind } from "./protocol";

/**
 * 면접 화면 상태머신 (docs/UI_SPEC.md §4.6.3). **서버가 상태의 단일 진실 원천**이며, 클라이언트는 서버 메시지를 렌더링하고
 * tts_done / answer_start / answer_end / gaze_event 만 보낸다. 전이는 순수 함수 `reduce` 로 구현해 브라우저 없이 테스트한다.
 *
 *   gate ─▶ connecting ─▶ ready ─▶ asking ─▶ countdown ─▶ answering ─▶ thinking ─▶ asking … ─▶ finished
 *                   ╲___________ reconnecting ◀── (연결 끊김, 어느 단계에서든) ──▶ failed / blocked
 */
export type Phase = "gate" | "connecting" | "ready" | "asking" | "countdown" | "answering" | "thinking" | "reconnecting" | "failed" | "blocked" | "finished";
export type FailureKind = "auth" | "forbidden" | "conflict" | "slot" | "inactive" | "network" | "protocol" | "device";

export interface Question {
  turnId: string; turnNo: number; kind: TurnKind; text: string;
  mainIndex: number; mainTotal: number; timeLimitSec: number; tts: boolean;
}

export interface InterviewState {
  phase: Phase;
  failure: { kind: FailureKind; message: string } | null;
  totalMain: number; answerLimitSec: number; maxFollowups: number; codingEnabled: boolean;
  question: Question | null;
  captionOnly: boolean;            // TTS 실패 → 자막만 (UI_SPEC §4.6.6)
  ttsPlaying: boolean;
  countdown: number | null;
  answerDeadline: number | null;   // 답변 마감 시각(클라이언트 epoch ms)
  thinkingStage: ThinkingStage | null;
  sttFinal: { text: string; lowConfidence: boolean } | null;
  liveTranscript: string;
  gaze: { count: number; message: string; visibleUntil: number } | null;
  gazeStatus: "unknown" | "ok" | "away" | "lost";
  degraded: string | null;
  notice: string | null;           // 복구 가능한 일시 안내 (STT 지연 등)
  micLevel: number;
  finishedNext: "coding" | "done" | null;
  reconnectAttempt: number;
}

export const initialState: InterviewState = {
  phase: "gate", failure: null, totalMain: 0, answerLimitSec: 0, maxFollowups: 0, codingEnabled: false,
  question: null, captionOnly: false, ttsPlaying: false, countdown: null, answerDeadline: null, thinkingStage: null,
  sttFinal: null, liveTranscript: "", gaze: null, gazeStatus: "unknown", degraded: null, notice: null, micLevel: 0,
  finishedNext: null, reconnectAttempt: 0,
};

export const GAZE_BANNER_MS = 5000;

/** 서버 메시지 → 상태 변화량. now 는 테스트 가능성을 위해 주입한다. */
export function reduce(s: InterviewState, m: ServerMessage, now: number): Partial<InterviewState> {
  switch (m.type) {
    case "session_ready":
      return {
        totalMain: m.total_main, answerLimitSec: m.answer_limit_sec, maxFollowups: m.max_followups, codingEnabled: m.coding_test.enabled,
        reconnectAttempt: 0, failure: null,
        // 연결 단계에서만 ready 로 간다 — 이미 진행 중인 단계를 덮어쓰지 않는다
        ...(s.phase === "connecting" || s.phase === "reconnecting" ? { phase: "ready" as const } : {}),
      };
    case "question": {
      const q: Question = {
        turnId: m.turn_id, turnNo: m.turn_no, kind: m.kind, text: m.text, mainIndex: m.progress.main, mainTotal: m.progress.total,
        timeLimitSec: m.time_limit_sec, tts: m.tts,
      };
      const common = { question: q, thinkingStage: null, sttFinal: null as InterviewState["sttFinal"], liveTranscript: "", notice: null };
      if (m.resumed) {
        // 답변 중 재접속: 낭독·카운트다운 없이 서버가 알려 준 남은 시간으로 답변을 이어간다
        return { ...common, phase: "answering", countdown: null, captionOnly: false, ttsPlaying: false, answerDeadline: now + m.time_limit_sec * 1000 };
      }
      return { ...common, phase: "asking", countdown: null, answerDeadline: null, captionOnly: !m.tts, ttsPlaying: false };
    }
    case "countdown":
      return { phase: "countdown", countdown: m.n, ttsPlaying: false, thinkingStage: null };
    case "stt_partial":
      return { liveTranscript: m.text };
    case "thinking":
      return { phase: "thinking", thinkingStage: m.stage, countdown: null, answerDeadline: null, ttsPlaying: false };
    case "stt_final":
      return { sttFinal: { text: m.text, lowConfidence: m.low_confidence }, liveTranscript: m.text };
    case "gaze_warning":
      return { gaze: { count: m.count, message: m.message, visibleUntil: now + GAZE_BANNER_MS } };
    case "degraded":
      return { degraded: m.message };
    case "session_finished":
      return { phase: "finished", finishedNext: m.next, countdown: null, answerDeadline: null, thinkingStage: null, ttsPlaying: false };
    case "error":
      switch (m.code) {
        case "TTS_FAILED": return { captionOnly: true, ttsPlaying: false };  // 세션은 계속 — 자막만 표시
        case "STT_FAILED": return { notice: m.message };
        case "ANSWER_TOO_SHORT": return { notice: m.message };  // 서버가 같은 질문의 카운트다운을 다시 보낸다
        default: return m.recoverable ? {} : { phase: "failed", failure: { kind: "protocol", message: m.message } };
      }
    default:
      return {};  // ack, ping, pong, tts_chunk 는 상태가 아니라 부수효과(훅)에서 처리
  }
}

interface Store extends InterviewState {
  apply: (m: ServerMessage, now?: number) => void;
  patch: (p: Partial<InterviewState>) => void;
  reset: () => void;
  /** 클라이언트가 answer_start 를 보낸 시점 */
  startAnswering: (limitSec: number, now?: number) => void;
  connectionLost: () => void;
}

export const useInterviewStore = create<Store>((set, get) => ({
  ...initialState,
  apply: (m, now = Date.now()) => set(reduce(get(), m, now)),
  patch: (p) => set(p),
  reset: () => set({ ...initialState }),
  startAnswering: (limitSec, now = Date.now()) => set({ phase: "answering", countdown: null, answerDeadline: now + limitSec * 1000 }),
  connectionLost: () => {
    set({ phase: "reconnecting", ttsPlaying: false, countdown: null });
  },
}));
