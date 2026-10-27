import { describe, expect, it } from "vitest";
import { GAZE, GazeCalibrator, GazeDetector, irisRatios, matrixToYawPitch, type GazeBase, type GazeEvent, type GazeSample } from "@/features/interview/gaze-logic";

const base: GazeBase = { yaw: 0, pitch: 0, irisX: 0.5, irisY: 0.5 };
const front = (t: number): GazeSample => ({ t, faces: 1, yaw: 0, pitch: 0, irisX: 0.5, irisY: 0.5 });
const away = (t: number): GazeSample => ({ t, faces: 1, yaw: 40, pitch: 0, irisX: 0.5, irisY: 0.5 });
const none = (t: number): GazeSample => ({ t, faces: 0 });

function run(samples: GazeSample[], origin = 0) {
  const events: GazeEvent[] = [];
  const d = new GazeDetector(base, (e) => events.push(e), origin);
  samples.forEach((s) => d.feed(s));
  return { events, d };
}
const ticks = (from: number, to: number, f: (t: number) => GazeSample) => { const out: GazeSample[] = []; for (let t = from; t <= to; t += 100) out.push(f(t)); return out; };

describe("GazeDetector", () => {
  it("does not fire for a short glance (<1.5s)", () => {
    const { events, d } = run([...ticks(0, 1000, away), ...ticks(1100, 3000, front)]);
    d.flush();
    expect(events).toEqual([]);
  });
  it("fires gaze_away once confirmed at 1.5s", () => {
    const { events } = run(ticks(0, 1600, away));
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ kind: "gaze_away", start_ms: 0 });
  });
  it("face_lost needs 2s", () => {
    expect(run(ticks(0, 1900, none)).events).toEqual([]);
    expect(run(ticks(0, 2100, none)).events[0]?.kind).toBe("face_lost");
  });
  it("multi_face fires at 1.5s", () => {
    expect(run(ticks(0, 1600, (t) => ({ t, faces: 2 }))).events[0]?.kind).toBe("multi_face");
  });
  it("segments a long away period every 3s and flush emits the rest; sum of durations equals the away time", () => {
    const { events, d } = run(ticks(0, 8000, away));
    d.flush();
    expect(events.length).toBeGreaterThanOrEqual(3);
    const total = events.reduce((a, e) => a + (e.end_ms - e.start_ms), 0);
    expect(total).toBeGreaterThanOrEqual(7800);
    expect(total).toBeLessThanOrEqual(8000);
    for (let i = 1; i < events.length; i++) expect(events[i]!.start_ms).toBeGreaterThanOrEqual(events[i - 1]!.end_ms);
  });
  it("merges a <1s gap into one continuing event (no close)", () => {
    const { events, d } = run([...ticks(0, 2000, away), ...ticks(2100, 2500, front), ...ticks(2600, 4000, away)]);
    d.flush();
    const lastEnd = events[events.length - 1]!.end_ms;
    expect(lastEnd).toBeGreaterThanOrEqual(3900);
  });
  it("closes after the gap exceeds 1s and re-arms", () => {
    const { events } = run([...ticks(0, 2000, away), ...ticks(2100, 3500, front)]);
    expect(events.length).toBeGreaterThan(0);
    expect(events[events.length - 1]!.end_ms).toBeLessThanOrEqual(2000);
  });
  it("times are relative to origin", () => {
    const { events } = run(ticks(10_000, 11_600, away).map((s) => ({ ...s })), 10_000);
    expect(events[0]?.start_ms).toBe(0);
  });
  it("reports status while confirmed", () => {
    const { d } = run(ticks(0, 1600, away));
    expect(d.status).toBe("gaze_away");
  });
  it("iris deviation alone triggers away", () => {
    const { events } = run(ticks(0, 1600, (t) => ({ t, faces: 1, yaw: 0, pitch: 0, irisX: 0.95, irisY: 0.5 })));
    expect(events[0]?.kind).toBe("gaze_away");
  });
});

describe("GazeCalibrator", () => {
  it("returns the mean after 2s of steady frontal samples", () => {
    const c = new GazeCalibrator();
    let b = null as GazeBase | null;
    for (let t = 0; t <= GAZE.calibrationMs && !b; t += 100) b = c.add({ t, faces: 1, yaw: 4, pitch: -2, irisX: 0.52, irisY: 0.48 });
    expect(b).toMatchObject({ yaw: 4, pitch: -2 });
  });
  it("restarts when the face disappears", () => {
    const c = new GazeCalibrator();
    for (let t = 0; t < 1500; t += 100) c.add(front(t));
    expect(c.add(none(1600))).toBeNull();
    expect(c.add(front(2200))).toBeNull();  // 2s 미충족: 리셋됨
  });
});

describe("geometry", () => {
  it("identity matrix → 0 yaw/pitch", () => {
    const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
    const r = matrixToYawPitch(I);
    expect(r.yaw).toBeCloseTo(0); expect(r.pitch).toBeCloseTo(0);
  });
  it("rotation about Y by 30° gives |yaw|=30", () => {
    const a = (30 * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
    // 열 우선 4x4, R_y(a): [[c,0,s],[0,1,0],[-s,0,c]]
    const m = [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1];
    expect(Math.abs(matrixToYawPitch(m).yaw)).toBeCloseTo(30, 1);
  });
  it("irisRatios returns null for too few landmarks and ~0.5 for centered irises", () => {
    expect(irisRatios(undefined)).toBeNull();
    expect(irisRatios(Array.from({ length: 10 }, () => ({ x: 0, y: 0 })))).toBeNull();
    const lm = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5 }));
    lm[33] = { x: 0.3, y: 0.5 }; lm[133] = { x: 0.5, y: 0.5 }; lm[468] = { x: 0.4, y: 0.5 };
    lm[362] = { x: 0.5, y: 0.5 }; lm[263] = { x: 0.7, y: 0.5 }; lm[473] = { x: 0.6, y: 0.5 };
    lm[159] = { x: 0.4, y: 0.45 }; lm[145] = { x: 0.4, y: 0.55 }; lm[386] = { x: 0.6, y: 0.45 }; lm[374] = { x: 0.6, y: 0.55 };
    lm[468] = { x: 0.4, y: 0.5 }; lm[473] = { x: 0.6, y: 0.5 };
    const r = irisRatios(lm)!;
    expect(r.irisX).toBeCloseTo(0.5, 5); expect(r.irisY).toBeCloseTo(0.5, 5);
  });
});
