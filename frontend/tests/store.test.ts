import { describe, expect, it } from "vitest";
import { initialState, reduce, type InterviewState } from "@/features/interview/store";
import type { ServerMessage } from "@/features/interview/protocol";

const env = { seq: 1, ts: "t" };
const msg = (m: object) => ({ ...env, ...m }) as ServerMessage;
const S = (p: Partial<InterviewState> = {}): InterviewState => ({ ...initialState, ...p });
const q = (extra: object = {}) => msg({ type: "question", turn_id: "t1", turn_no: 1, kind: "main", text: "자기소개", progress: { main: 1, total: 5 }, time_limit_sec: 120, tts: true, resumed: false, ...extra });

describe("reduce", () => {
  it("session_ready moves connecting → ready but never overwrites a running phase", () => {
    const ready = msg({ type: "session_ready", total_main: 5, answer_limit_sec: 120, max_followups: 2, coding_test: { enabled: true, time_limit_sec: 600 } });
    expect(reduce(S({ phase: "connecting" }), ready, 0)).toMatchObject({ phase: "ready", totalMain: 5, codingEnabled: true });
    expect(reduce(S({ phase: "reconnecting" }), ready, 0).phase).toBe("ready");
    expect(reduce(S({ phase: "answering" }), ready, 0).phase).toBeUndefined();
  });
  it("question → asking with caption immediately; tts=false means captionOnly", () => {
    expect(reduce(S({ phase: "ready" }), q(), 0)).toMatchObject({ phase: "asking", captionOnly: false, question: { text: "자기소개", mainIndex: 1 } });
    expect(reduce(S(), q({ tts: false }), 0).captionOnly).toBe(true);
  });
  it("resumed question goes straight to answering with the remaining time", () => {
    const r = reduce(S({ phase: "reconnecting" }), q({ resumed: true, time_limit_sec: 45 }), 1000);
    expect(r).toMatchObject({ phase: "answering", answerDeadline: 1000 + 45_000, ttsPlaying: false });
  });
  it("countdown / thinking / finished transitions", () => {
    expect(reduce(S({ phase: "asking" }), msg({ type: "countdown", turn_id: "t1", n: 3 }), 0)).toMatchObject({ phase: "countdown", countdown: 3 });
    expect(reduce(S({ phase: "answering", answerDeadline: 5 }), msg({ type: "thinking", turn_id: "t1", stage: "stt" }), 0)).toMatchObject({ phase: "thinking", answerDeadline: null });
    expect(reduce(S(), msg({ type: "session_finished", next: "coding" }), 0)).toMatchObject({ phase: "finished", finishedNext: "coding" });
  });
  it("gaze_warning shows a banner for 5s", () => {
    expect(reduce(S(), msg({ type: "gaze_warning", count: 2, message: "m" }), 100).gaze).toEqual({ count: 2, message: "m", visibleUntil: 5100 });
  });
  it("error handling: TTS_FAILED keeps session, ANSWER_TOO_SHORT/STT_FAILED notice, unrecoverable fails", () => {
    const err = (code: string, recoverable: boolean) => msg({ type: "error", code, recoverable, message: "x" });
    expect(reduce(S({ phase: "asking" }), err("TTS_FAILED", true), 0)).toMatchObject({ captionOnly: true });
    expect(reduce(S(), err("ANSWER_TOO_SHORT", true), 0).notice).toBe("x");
    expect(reduce(S(), err("STT_FAILED", true), 0).notice).toBe("x");
    expect(reduce(S(), err("BAD_FRAME", false), 0)).toMatchObject({ phase: "failed" });
    expect(reduce(S(), err("WHATEVER", true), 0)).toEqual({});
  });
  it("non-state messages produce no change", () => {
    expect(reduce(S(), msg({ type: "ping" }), 0)).toEqual({});
    expect(reduce(S(), msg({ type: "ack", ack_seq: 3, missing: 0 }), 0)).toEqual({});
  });
  it("a new question clears the previous answer's transcript and notice", () => {
    const r = reduce(S({ liveTranscript: "old", notice: "n", sttFinal: { text: "a", lowConfidence: false } }), q(), 0);
    expect(r).toMatchObject({ liveTranscript: "", notice: null, sttFinal: null });
  });
});
