import { describe, expect, it } from "vitest";
import { CHUNK_SAMPLES, LinearResampler, PcmChunker, floatToInt16, rmsLevel } from "@/features/interview/pcm";

describe("floatToInt16", () => {
  it("maps range and clips", () => {
    expect(Array.from(floatToInt16(Float32Array.from([0, 1, -1, 2, -2])))).toEqual([0, 32767, -32768, 32767, -32768]);
  });
});

describe("PcmChunker", () => {
  it("emits exact 500ms chunks and carries the remainder", () => {
    const c = new PcmChunker();
    expect(c.push(new Int16Array(CHUNK_SAMPLES - 1))).toHaveLength(0);
    const out = c.push(new Int16Array(CHUNK_SAMPLES + 1));
    expect(out).toHaveLength(2);
    expect(out.every((x) => x.length === CHUNK_SAMPLES)).toBe(true);
    expect(c.pending).toBe(0);
  });
  it("preserves sample order across pushes", () => {
    const c = new PcmChunker(4);
    c.push(Int16Array.from([1, 2, 3]));
    const [chunk] = c.push(Int16Array.from([4, 5]));
    expect(Array.from(chunk!)).toEqual([1, 2, 3, 4]);
    expect(c.pending).toBe(1);
  });
});

describe("rmsLevel", () => {
  it("is 0 for silence/empty and capped at 1", () => {
    expect(rmsLevel(new Float32Array(0))).toBe(0);
    expect(rmsLevel(new Float32Array(100))).toBe(0);
    expect(rmsLevel(new Float32Array(100).fill(1))).toBe(1);
  });
});

describe("LinearResampler", () => {
  it("is identity at the same rate", () => {
    const x = Float32Array.from([0.1, 0.2]);
    expect(new LinearResampler(16000).process(x)).toBe(x);
  });
  it("48k→16k yields ~1/3 of the samples, and chunking does not change the total", () => {
    const input = Float32Array.from({ length: 4800 }, (_, i) => Math.sin(i / 20));
    const whole = new LinearResampler(48000).process(input).length;
    const r = new LinearResampler(48000);
    let split = 0;
    for (let i = 0; i < input.length; i += 480) split += r.process(input.subarray(i, i + 480)).length;
    expect(Math.abs(whole - 1600)).toBeLessThanOrEqual(1);
    expect(Math.abs(split - whole)).toBeLessThanOrEqual(1);
  });
  it("interpolates a linear ramp exactly across chunk boundaries", () => {
    const ramp = Float32Array.from({ length: 300 }, (_, i) => i);
    const r = new LinearResampler(48000);
    const out = [...r.process(ramp.subarray(0, 100)), ...r.process(ramp.subarray(100, 300))];
    out.forEach((v, i) => expect(v).toBeCloseTo(i * 3, 3));
  });
});
