/**
 * WebSocket 제어/미디어 프로토콜 (docs/TRD.md §4.1, §7.7). 백엔드 `app/schemas/ws.py` 와 1:1 로 대응한다.
 * WebSocket 메시지는 OpenAPI 에 나타나지 않으므로 이 파일을 손으로 관리한다 — 백엔드 스키마를 바꾸면 여기와
 * tests/protocol.test.ts 도 함께 바꿔야 한다.
 */
export type TurnKind = "main" | "followup" | "code_followup";
export type ThinkingStage = "stt" | "analysis" | "generation";

interface Envelope { seq: number; ts: string }

export type ServerMessage = Envelope & (
  | { type: "session_ready"; total_main: number; answer_limit_sec: number; max_followups: number; coding_test: { enabled: boolean; time_limit_sec: number | null } }
  | { type: "question"; turn_id: string; turn_no: number; kind: TurnKind; text: string; progress: { main: number; total: number }; time_limit_sec: number; tts: boolean; resumed: boolean }
  | { type: "tts_chunk"; turn_id: string; idx: number; last: boolean; format: "wav" | "mp3"; data_b64: string }
  | { type: "countdown"; turn_id: string; n: number }
  | { type: "stt_partial"; turn_id: string; text: string }
  | { type: "thinking"; turn_id: string | null; stage: ThinkingStage }
  | { type: "stt_final"; turn_id: string; text: string; low_confidence: boolean }
  | { type: "gaze_warning"; count: number; message: string }
  | { type: "degraded"; reason: string; message: string }
  | { type: "error"; code: string; recoverable: boolean; message: string }
  | { type: "session_finished"; next: "coding" | "done" }
  | { type: "ack"; ack_seq: number; missing: number }
  | { type: "ping" }
  | { type: "pong" }
);

export type GazeKind = "gaze_away" | "face_lost" | "multi_face";
export type ClientMessage =
  | { type: "tts_done"; turn_id: string }
  | { type: "answer_start"; turn_id: string }
  | { type: "answer_end"; turn_id: string; reason: "user" | "timeout" }
  | { type: "text_answer"; turn_id: string; text: string }
  | { type: "gaze_event"; turn_id: string; kind: GazeKind; start_ms: number; end_ms: number; yaw?: number; pitch?: number; confidence?: number }
  | { type: "resume"; last_turn_id: string | null }
  | { type: "ping" }
  | { type: "pong" };

/** 필수 필드 검사표. 서버가 보내는 값이라도 형식이 어긋나면 UI 가 깨지지 않도록 무시한다. */
const REQUIRED: Record<ServerMessage["type"], [string, string][]> = {
  session_ready: [["total_main", "number"], ["answer_limit_sec", "number"], ["max_followups", "number"], ["coding_test", "object"]],
  question: [["turn_id", "string"], ["turn_no", "number"], ["kind", "string"], ["text", "string"], ["progress", "object"], ["time_limit_sec", "number"]],
  tts_chunk: [["turn_id", "string"], ["idx", "number"], ["last", "boolean"], ["data_b64", "string"]],
  countdown: [["turn_id", "string"], ["n", "number"]],
  stt_partial: [["turn_id", "string"], ["text", "string"]],
  thinking: [["stage", "string"]],
  stt_final: [["turn_id", "string"], ["text", "string"], ["low_confidence", "boolean"]],
  gaze_warning: [["count", "number"], ["message", "string"]],
  degraded: [["reason", "string"], ["message", "string"]],
  error: [["code", "string"], ["recoverable", "boolean"], ["message", "string"]],
  session_finished: [["next", "string"]],
  ack: [["ack_seq", "number"]],
  ping: [], pong: [],
};

export function parseServerMessage(raw: unknown): ServerMessage | null {
  if (typeof raw !== "string") return null;
  let obj: unknown;
  try { obj = JSON.parse(raw); } catch { return null; }
  if (typeof obj !== "object" || obj === null) return null;
  const m = obj as Record<string, unknown>;
  const type = m["type"];
  if (typeof type !== "string" || !(type in REQUIRED)) return null;
  for (const [key, t] of REQUIRED[type as ServerMessage["type"]]) {
    if (typeof m[key] !== t || (t === "object" && m[key] === null)) return null;
  }
  return m as unknown as ServerMessage;
}

/** WebSocket close code (TRD §4.1) */
export const CLOSE = { PROTOCOL: 4400, UNAUTHORIZED: 4401, FORBIDDEN: 4403, NOT_FOUND: 4404, IDLE: 4408, CONFLICT: 4409 } as const;

/** 미디어 프레임 `[1B type][4B seq uint32 BE][payload]` (TRD §7.7) */
export const FRAME = { AUDIO: 0x01, VIDEO: 0x02 } as const;
export const MAX_SEQ = 0xffff_ffff;

export function buildFrame(type: number, seq: number, payload: ArrayBufferLike): ArrayBuffer {
  if (!Number.isInteger(seq) || seq < 0 || seq > MAX_SEQ) throw new RangeError("seq must be uint32");
  const body = new Uint8Array(payload);
  const out = new Uint8Array(5 + body.byteLength);
  out[0] = type;
  new DataView(out.buffer).setUint32(1, seq, false);  // big-endian
  out.set(body, 5);
  return out.buffer;
}

export const buildAudioFrame = (seq: number, pcm: Int16Array) =>
  buildFrame(FRAME.AUDIO, seq, pcm.buffer.slice(pcm.byteOffset, pcm.byteOffset + pcm.byteLength));
export const buildVideoFrame = (seq: number, data: ArrayBuffer) => buildFrame(FRAME.VIDEO, seq, data);

export function wsBase(): string {
  const env = process.env.NEXT_PUBLIC_WS_URL;
  if (env) return env.replace(/\/$/, "");
  if (typeof window === "undefined") return "";
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.hostname}:8000`;
}

/** 재접속 대기 시간: 1→2→4s, 이후 4s 고정, 최대 5회 (UI_SPEC §4.6.6). attempt 는 1부터. 한도를 넘으면 null. */
export const MAX_RECONNECT = 5;
export function backoffMs(attempt: number): number | null {
  if (attempt < 1 || attempt > MAX_RECONNECT) return null;
  return [1000, 2000, 4000, 4000, 4000][attempt - 1] ?? null;
}
