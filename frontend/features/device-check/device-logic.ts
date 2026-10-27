/** 사전 환경 점검의 순수 로직 (UI_SPEC §4.5.3). React/브라우저 API 에 의존하지 않아 단위 테스트가 가능하다. */
import type { GazeBase } from "@/features/interview/gaze-logic";

export type Step = "camera" | "mic" | "speaker";
export type StepStatus = "idle" | "checking" | "pass" | "fail";
export type StepStates = Record<Step, StepStatus>;

export const STEPS: Step[] = ["camera", "mic", "speaker"];
export const STEP_LABEL: Record<Step, string> = { camera: "카메라", mic: "마이크", speaker: "스피커" };

export const MIC_THRESHOLD_DB = -50;   // 입력으로 인정하는 최소 레벨 (dBFS)
export const MIC_REQUIRED_MS = 500;    // 임계 이상 입력이 누적 0.5초 이상이면 통과
export const MIC_SILENCE_HINT_MS = 5000;

export const initialStates = (): StepStates => ({ camera: "idle", mic: "idle", speaker: "idle" });

/** 순서 고정(PRE-3): 앞 단계가 통과해야 다음 단계가 열린다. 모두 통과하면 null. */
export function activeStep(s: StepStates): Step | null {
  return STEPS.find((k) => s[k] !== "pass") ?? null;
}
export const allPassed = (s: StepStates): boolean => STEPS.every((k) => s[k] === "pass");
export const isUnlocked = (s: StepStates, step: Step): boolean => STEPS.slice(0, STEPS.indexOf(step)).every((k) => s[k] === "pass");

/** 한 단계를 다시 점검하면 그 단계와 뒤 단계가 초기화된다. */
export function resetFrom(s: StepStates, from: Step): StepStates {
  const next = { ...s };
  for (const k of STEPS.slice(STEPS.indexOf(from))) next[k] = "idle";
  return next;
}

export const rmsToDb = (rms: number): number => 20 * Math.log10(Math.max(rms, 1e-8));

export function rmsOfSamples(buf: ArrayLike<number>): number {
  if (buf.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i]! * buf[i]!;
  return Math.sqrt(sum / buf.length);
}

/** dBFS(-60~-10)를 0~1 미터 값으로 */
export const dbToMeter = (db: number): number => Math.min(1, Math.max(0, (db + 60) / 50));

/** 임계 이상 입력의 누적 시간으로 통과를 판정하고, 무음이 이어지면 안내 플래그를 올린다. */
export class MicDetector {
  private loudMs = 0;
  private quietMs = 0;
  constructor(private readonly thresholdDb = MIC_THRESHOLD_DB, private readonly requiredMs = MIC_REQUIRED_MS, private readonly silenceHintMs = MIC_SILENCE_HINT_MS) {}

  feed(db: number, dtMs: number): { passed: boolean; silent: boolean } {
    if (db >= this.thresholdDb) { this.loudMs += dtMs; this.quietMs = 0; }
    else this.quietMs += dtMs;
    return { passed: this.loudMs >= this.requiredMs, silent: this.loudMs < this.requiredMs && this.quietMs >= this.silenceHintMs };
  }
  reset(): void { this.loudMs = 0; this.quietMs = 0; }
}

// ── 선택한 장치·정면 보정값은 새로고침/면접 화면과 공유하기 위해 sessionStorage 에 둔다 (탭을 닫으면 사라진다) ──
const DEVICE_KEY = "ai-interview:devices";
const GAZE_KEY = (sessionId: string) => `ai-interview:gaze-base:${sessionId}`;

export interface DeviceChoice { video?: string; audio?: string; output?: string }

function store(): Storage | null {
  try { return typeof window === "undefined" ? null : window.sessionStorage; } catch { return null; }
}

export function saveDeviceChoice(c: DeviceChoice): void {
  try { store()?.setItem(DEVICE_KEY, JSON.stringify(c)); } catch { /* 저장 불가 환경에서는 기본 장치를 쓴다 */ }
}
export function readDeviceChoice(): DeviceChoice {
  try {
    const raw = store()?.getItem(DEVICE_KEY);
    const v = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    const pick = (k: string) => (typeof v[k] === "string" && v[k] ? (v[k] as string) : undefined);
    return { video: pick("video"), audio: pick("audio"), output: pick("output") };
  } catch { return {}; }
}

const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
export function saveGazeBase(sessionId: string, b: GazeBase): void {
  try { store()?.setItem(GAZE_KEY(sessionId), JSON.stringify(b)); } catch { /* 보정값이 없으면 면접 화면에서 다시 보정한다 */ }
}
export function readGazeBase(sessionId: string): GazeBase | null {
  try {
    const raw = store()?.getItem(GAZE_KEY(sessionId));
    const v = raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
    return v && isNum(v.yaw) && isNum(v.pitch) && isNum(v.irisX) && isNum(v.irisY) ? { yaw: v.yaw, pitch: v.pitch, irisX: v.irisX, irisY: v.irisY } : null;
  } catch { return null; }
}

/** 단계 안내 문구에 쓰는 getUserMedia 오류 → 사용자 안내 (UI_SPEC §4.5.6) */
export function mediaErrorHint(name: string, kind: "camera" | "mic"): string {
  const what = kind === "camera" ? "카메라" : "마이크";
  switch (name) {
    case "NotAllowedError": return `${what} 권한이 거부되었습니다. 주소창 왼쪽의 권한 설정에서 ${what}를 허용한 뒤 [다시 시도]를 눌러 주세요.`;
    case "NotFoundError": return `${what}를 찾을 수 없어요. 장치를 연결한 뒤 [다시 검색]을 눌러 주세요.`;
    case "NotReadableError": return `다른 앱이 ${what}를 사용 중입니다. 해당 앱을 닫고 다시 시도해 주세요.`;
    case "OverconstrainedError": return `선택한 ${what}를 사용할 수 없어요. 다른 장치를 선택해 주세요.`;
    case "SecurityError": return "보안 연결(HTTPS)에서만 장치를 사용할 수 있어요. 관리자에게 문의해 주세요.";
    default: return `${what}를 사용할 수 없어요. 장치를 확인한 뒤 다시 시도해 주세요.`;
  }
}

/** 안내 음성: 짧은 3음 차임 WAV (16-bit mono). 외부 파일·네트워크 없이 로컬에서 만든다. */
export function makeChimeWav(rate = 22050): Uint8Array {
  const notes = [523.25, 659.25, 783.99];  // C5 E5 G5
  const noteSec = 0.38;
  const n = Math.floor(rate * noteSec * notes.length);
  const pcm = new Int16Array(n);
  notes.forEach((hz, k) => {
    const start = Math.floor(rate * noteSec * k), len = Math.floor(rate * noteSec);
    for (let i = 0; i < len; i++) {
      const env = Math.min(1, i / (rate * 0.02)) * Math.min(1, (len - i) / (rate * 0.12));
      pcm[start + i] = Math.round(9000 * env * Math.sin((2 * Math.PI * hz * i) / rate));
    }
  });
  const out = new Uint8Array(44 + pcm.length * 2);
  const dv = new DataView(out.buffer);
  const tag = (o: number, s: string) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  tag(0, "RIFF"); dv.setUint32(4, 36 + pcm.length * 2, true); tag(8, "WAVE"); tag(12, "fmt ");
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, rate, true);
  dv.setUint32(28, rate * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); tag(36, "data"); dv.setUint32(40, pcm.length * 2, true);
  pcm.forEach((s, i) => dv.setInt16(44 + i * 2, s, true));
  return out;
}

// ── 면접 시작(`POST /sessions/{id}/start`) 응답 해석 ──
export const START_TIMEOUT_MS = 60_000;
export const START_STAGE_TEXT: Record<string, string> = {
  preparing: "이력서를 분석하고 질문을 준비하고 있어요",
  warming: "AI 면접관을 준비하고 있어요 (모델 로딩)",
};
