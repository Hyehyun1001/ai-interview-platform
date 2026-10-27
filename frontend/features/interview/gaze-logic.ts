/**
 * 시선 이탈 판정 (docs/TRD.md §4.4). 브라우저·MediaPipe 에 의존하지 않는 순수 로직이라 합성 샘플로 단위 테스트한다.
 *
 * 판정: head yaw/pitch 편차 또는 홍채 위치 편차가 임계값을 넘는 상태가 연속 1.5초 이상이면 gaze_away, 얼굴 미검출이 2초 이상이면
 * face_lost, 얼굴이 둘 이상이면 multi_face. 이탈이 끝난 뒤 1초 안에 다시 발생하면 하나의 이벤트로 병합한다.
 *
 * **구간 분할 전송:** 서버의 gaze_warning 은 gaze_event 를 받아야 나가므로, 이탈이 끝나길 기다리면 경고가 답변이 끝난 뒤에야 도착한다.
 * 그래서 확정 시점부터 SEGMENT_MS(3초)마다 [lastEmit, now] 구간을 잘라 보내고, 종료 시 남은 구간을 보낸다. 구간 길이의 합 = 실제 이탈 시간
 * 이므로 이탈률(Σ지속시간/Σ답변시간)은 그대로 정확하다.
 */
export type GazeKind = "gaze_away" | "face_lost" | "multi_face";

export interface GazeBase { yaw: number; pitch: number; irisX: number; irisY: number }
/** t: 단조 시계(ms). faces: 검출된 얼굴 수. 얼굴이 하나일 때만 yaw/pitch/iris 가 의미 있다. */
export interface GazeSample { t: number; faces: number; yaw?: number; pitch?: number; irisX?: number; irisY?: number }
export interface GazeEvent { kind: GazeKind; start_ms: number; end_ms: number; yaw?: number; pitch?: number }

export const GAZE = {
  yawDeg: 25, pitchDeg: 20, irisDev: 0.35,
  awayMs: 1500, faceLostMs: 2000, multiFaceMs: 1500,
  mergeMs: 1000, segmentMs: 3000, calibrationMs: 2000, calibrationMinSamples: 5,
} as const;

const CONFIRM_MS: Record<GazeKind, number> = { gaze_away: GAZE.awayMs, face_lost: GAZE.faceLostMs, multi_face: GAZE.multiFaceMs };

/** MediaPipe facialTransformationMatrixes(4x4, 열 우선) → yaw/pitch(도). r_ij = m[i + 4j], ZYX 분해. 부호 규약은 기준값(보정)과의 편차만 쓰므로 무관하다. */
export function matrixToYawPitch(m: ArrayLike<number>): { yaw: number; pitch: number } {
  const r = (i: number, j: number) => m[i + 4 * j] ?? 0;
  const deg = 180 / Math.PI;
  return { pitch: Math.atan2(r(2, 1), r(2, 2)) * deg, yaw: Math.atan2(-r(2, 0), Math.hypot(r(2, 1), r(2, 2))) * deg };
}

interface Pt { x: number; y: number }
// MediaPipe Face Mesh(홍채 포함 478점) 인덱스
const LM = { rIris: 468, lIris: 473, rOuter: 33, rInner: 133, lInner: 362, lOuter: 263, rUp: 159, rLow: 145, lUp: 386, lLow: 374 } as const;

/** 눈 가로/세로 폭 대비 홍채 중심 위치(0~1, 정면≈0.5). 랜드마크가 부족하면 null. */
export function irisRatios(lm: ArrayLike<Pt> | undefined): { irisX: number; irisY: number } | null {
  if (!lm || lm.length <= LM.lIris) return null;
  const p = (i: number) => lm[i] as Pt;
  const ratio = (v: number, a: number, b: number) => (b - a === 0 ? 0.5 : (v - a) / (b - a));
  const rx = ratio(p(LM.rIris).x, p(LM.rOuter).x, p(LM.rInner).x);
  const lx = ratio(p(LM.lIris).x, p(LM.lInner).x, p(LM.lOuter).x);
  const ry = ratio(p(LM.rIris).y, p(LM.rUp).y, p(LM.rLow).y);
  const ly = ratio(p(LM.lIris).y, p(LM.lUp).y, p(LM.lLow).y);
  return { irisX: (rx + lx) / 2, irisY: (ry + ly) / 2 };
}

/** 정면 응시 2초의 평균을 개인 기준값으로 삼는다. 얼굴이 하나가 아니거나 값이 없으면 처음부터 다시 모은다. */
export class GazeCalibrator {
  private first: number | null = null;
  private n = 0;
  private sum = { yaw: 0, pitch: 0, irisX: 0, irisY: 0 };

  add(s: GazeSample): GazeBase | null {
    if (s.faces !== 1 || s.yaw === undefined || s.pitch === undefined || s.irisX === undefined || s.irisY === undefined) {
      this.reset();
      return null;
    }
    this.first ??= s.t;
    this.n++;
    this.sum.yaw += s.yaw; this.sum.pitch += s.pitch; this.sum.irisX += s.irisX; this.sum.irisY += s.irisY;
    if (s.t - this.first >= GAZE.calibrationMs && this.n >= GAZE.calibrationMinSamples) {
      const n = this.n;
      return { yaw: this.sum.yaw / n, pitch: this.sum.pitch / n, irisX: this.sum.irisX / n, irisY: this.sum.irisY / n };
    }
    return null;
  }

  reset(): void { this.first = null; this.n = 0; this.sum = { yaw: 0, pitch: 0, irisX: 0, irisY: 0 }; }
}

function condition(s: GazeSample, base: GazeBase): GazeKind | null {
  if (s.faces === 0) return "face_lost";
  if (s.faces > 1) return "multi_face";
  const dYaw = Math.abs((s.yaw ?? base.yaw) - base.yaw);
  const dPitch = Math.abs((s.pitch ?? base.pitch) - base.pitch);
  const dIris = Math.max(Math.abs((s.irisX ?? base.irisX) - base.irisX), Math.abs((s.irisY ?? base.irisY) - base.irisY));
  return dYaw > GAZE.yawDeg || dPitch > GAZE.pitchDeg || dIris > GAZE.irisDev ? "gaze_away" : null;
}

interface Active { kind: GazeKind; lastEmit: number; lastTrue: number; yaw?: number; pitch?: number }

export class GazeDetector {
  private cand: { kind: GazeKind; since: number } | null = null;
  private active: Active | null = null;

  /** origin: 답변 시작 시각(같은 단조 시계). 이벤트 시간은 이 값 기준 상대 ms (TRD §4.4). */
  constructor(private readonly base: GazeBase, private readonly emit: (e: GazeEvent) => void, private readonly origin: number) {}

  /** 현재 이탈이 확정된 상태인지 (UI 의 시선 상태 점 표시용) */
  get status(): GazeKind | null { return this.active?.kind ?? null; }

  feed(s: GazeSample): void {
    const c = condition(s, this.base);
    const a = this.active;
    if (a) {
      if (c === a.kind) {
        a.lastTrue = s.t;
        if (s.faces === 1) { a.yaw = (s.yaw ?? this.base.yaw) - this.base.yaw; a.pitch = (s.pitch ?? this.base.pitch) - this.base.pitch; }
        if (s.t - a.lastEmit >= GAZE.segmentMs) this.emitSegment(a, s.t);
        return;
      }
      if (s.t - a.lastTrue < GAZE.mergeMs) return;  // 1초 이내 재발생이면 같은 이벤트로 병합 (잠시 정상이어도 닫지 않는다)
      this.emitSegment(a, a.lastTrue);
      this.active = null;
    }
    if (c === null) { this.cand = null; return; }
    if (!this.cand || this.cand.kind !== c) this.cand = { kind: c, since: s.t };
    if (s.t - this.cand.since >= CONFIRM_MS[c]) {
      const next: Active = { kind: c, lastEmit: this.cand.since, lastTrue: s.t };
      if (s.faces === 1) { next.yaw = (s.yaw ?? this.base.yaw) - this.base.yaw; next.pitch = (s.pitch ?? this.base.pitch) - this.base.pitch; }
      this.active = next;
      this.cand = null;
      this.emitSegment(next, s.t);  // 확정 즉시 첫 구간을 보내 서버 경고가 지연되지 않게 한다
    }
  }

  /** 답변 종료 시 호출: 진행 중인 이탈의 남은 구간을 내보낸다. */
  flush(): void {
    if (this.active) this.emitSegment(this.active, this.active.lastTrue);
    this.active = null;
    this.cand = null;
  }

  private emitSegment(a: Active, endT: number): void {
    if (endT <= a.lastEmit) return;
    const ev: GazeEvent = { kind: a.kind, start_ms: Math.max(0, Math.round(a.lastEmit - this.origin)), end_ms: Math.max(0, Math.round(endT - this.origin)) };
    if (a.yaw !== undefined) ev.yaw = Math.round(a.yaw * 10) / 10;
    if (a.pitch !== undefined) ev.pitch = Math.round(a.pitch * 10) / 10;
    a.lastEmit = endT;
    this.emit(ev);
  }
}
