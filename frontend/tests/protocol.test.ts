import { describe, expect, it } from "vitest";
import { FRAME, backoffMs, buildAudioFrame, buildFrame, parseServerMessage } from "@/features/interview/protocol";

const env = { seq: 1, ts: "2026-01-01T00:00:00Z" };

describe("parseServerMessage", () => {
  it("accepts a valid message", () => {
    const m = parseServerMessage(JSON.stringify({ ...env, type: "countdown", turn_id: "t", n: 3 }));
    expect(m?.type).toBe("countdown");
  });
  it.each([
    ["not json", "{"],
    ["unknown type", JSON.stringify({ ...env, type: "nope" })],
    ["missing field", JSON.stringify({ ...env, type: "countdown", turn_id: "t" })],
    ["wrong field type", JSON.stringify({ ...env, type: "countdown", turn_id: "t", n: "3" })],
    ["array", "[]"], ["null", "null"],
  ])("rejects %s", (_n, raw) => expect(parseServerMessage(raw)).toBeNull());
  it("rejects non-string frames (binary)", () => expect(parseServerMessage(new ArrayBuffer(4))).toBeNull());
});

describe("frame builders", () => {
  it("layout is [type][seq u32 BE][payload]", () => {
    const f = new Uint8Array(buildFrame(FRAME.VIDEO, 0x01020304, new Uint8Array([9, 8]).buffer));
    expect(Array.from(f)).toEqual([0x02, 1, 2, 3, 4, 9, 8]);
  });
  it("audio frame carries PCM bytes little-endian as-is", () => {
    const f = new Uint8Array(buildAudioFrame(0, new Int16Array([1, -1])));
    expect(f.length).toBe(5 + 4);
    expect(f[0]).toBe(FRAME.AUDIO);
  });
  it("audio frame respects subarray offsets", () => {
    const big = new Int16Array([7, 8, 9, 10]);
    const f = new Uint8Array(buildAudioFrame(5, big.subarray(1, 3)));
    expect(f.length).toBe(5 + 4);
    expect(f[5]).toBe(8);
  });
  it("rejects seq outside uint32", () => {
    expect(() => buildFrame(1, -1, new ArrayBuffer(0))).toThrow(RangeError);
    expect(() => buildFrame(1, 2 ** 32, new ArrayBuffer(0))).toThrow(RangeError);
    expect(() => buildFrame(1, 1.5, new ArrayBuffer(0))).toThrow(RangeError);
  });
});

describe("backoffMs", () => {
  it("1,2,4,4,4 then gives up", () => {
    expect([1, 2, 3, 4, 5].map(backoffMs)).toEqual([1000, 2000, 4000, 4000, 4000]);
    expect(backoffMs(6)).toBeNull();
    expect(backoffMs(0)).toBeNull();
  });
});
