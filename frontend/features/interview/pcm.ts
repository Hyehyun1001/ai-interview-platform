/**
 * 마이크 오디오 → 서버 규격 변환 (TRD §4.2): 16kHz mono PCM16, 500ms(8,000 샘플 = 16,000 바이트) 청크.
 * AudioContext 를 16kHz 로 만들면 브라우저가 리샘플링하므로 여기서는 float → int16 변환과 청크 분할만 한다.
 */
export const SAMPLE_RATE = 16_000;
export const CHUNK_SAMPLES = 8_000;  // 500ms

export function floatToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i] ?? 0));
    out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
  }
  return out;
}

/** 임의 길이의 샘플을 받아 정확히 samplesPerChunk 개씩의 청크로 내보낸다. 남는 샘플은 다음 호출로 이월한다. */
export class PcmChunker {
  private buf = new Int16Array(0);
  constructor(private readonly samplesPerChunk = CHUNK_SAMPLES) {}

  push(samples: Int16Array): Int16Array[] {
    const merged = new Int16Array(this.buf.length + samples.length);
    merged.set(this.buf);
    merged.set(samples, this.buf.length);
    const out: Int16Array[] = [];
    let off = 0;
    while (merged.length - off >= this.samplesPerChunk) {
      out.push(merged.slice(off, off + this.samplesPerChunk));
      off += this.samplesPerChunk;
    }
    this.buf = merged.slice(off);
    return out;
  }

  get pending(): number { return this.buf.length; }
  reset(): void { this.buf = new Int16Array(0); }
}

/** 0~1 로 정규화한 RMS 레벨 (마이크 미터용). */
export function rmsLevel(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += (samples[i] ?? 0) ** 2;
  return Math.min(1, Math.sqrt(sum / samples.length) * 4);  // 일반 발화(RMS≈0.05~0.25)가 미터 중간 이상에 오도록 스케일
}

/**
 * 컨텍스트 샘플레이트가 16kHz 가 아닐 때(일부 브라우저는 AudioContext 의 sampleRate 옵션을 무시) 쓰는 선형 보간 리샘플러.
 * 스트리밍 입력의 경계에서 소수 위치와 마지막 샘플을 이월해 청크 경계에 끊김이 생기지 않는다.
 */
export class LinearResampler {
  private pos = 0;                 // 다음 출력 샘플의 입력 상 위치 (현재 입력 청크 기준)
  private last = 0;                // 직전 청크의 마지막 샘플
  private readonly step: number;
  constructor(fromRate: number, toRate = SAMPLE_RATE) { this.step = fromRate / toRate; }

  process(input: Float32Array): Float32Array {
    if (this.step === 1) return input;
    const out: number[] = [];
    // 인덱스 -1 은 직전 청크의 마지막 샘플
    const at = (i: number) => (i < 0 ? this.last : (input[i] ?? 0));
    while (this.pos < input.length - 1) {
      const i = Math.floor(this.pos);
      const f = this.pos - i;
      out.push(at(i) * (1 - f) + at(i + 1) * f);
      this.pos += this.step;
    }
    this.pos -= input.length;
    this.last = input[input.length - 1] ?? this.last;
    return Float32Array.from(out);
  }
}
