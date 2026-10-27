"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { buildAudioFrame, buildVideoFrame, backoffMs, wsBase } from "./protocol";
import { CHUNK_SAMPLES, LinearResampler, PcmChunker, SAMPLE_RATE, floatToInt16, rmsLevel } from "./pcm";
import { readDeviceChoice } from "@/features/device-check/device-logic";
import { useInterviewStore } from "./store";

export type MediaStatus = "idle" | "requesting" | "ready" | "error";
export interface MediaError { name: string; message: string }

const UNACKED_MAX = 20;  // 500ms 청크 20개 = 10초: 미디어 연결이 잠깐 끊겨도 재전송할 수 있는 버퍼 (UI_SPEC §4.6.6)
const LEVEL_INTERVAL_MS = 80;

/** getUserMedia 오류 → 사용자 안내 (UI_SPEC §4.5.6) */
export function describeMediaError(e: unknown): MediaError {
  const name = e instanceof DOMException ? e.name : "UnknownError";
  const map: Record<string, string> = {
    NotAllowedError: "카메라·마이크 권한이 거부되었습니다. 브라우저 주소창의 권한 설정에서 허용한 뒤 다시 시도해 주세요.",
    NotFoundError: "카메라 또는 마이크를 찾을 수 없습니다. 장치를 연결한 뒤 다시 시도해 주세요.",
    NotReadableError: "다른 앱이 카메라·마이크를 사용 중입니다. 해당 앱을 닫고 다시 시도해 주세요.",
    OverconstrainedError: "선택한 장치를 사용할 수 없습니다. 다른 장치를 선택해 주세요.",
    SecurityError: "보안 연결(HTTPS)에서만 카메라·마이크를 사용할 수 있습니다.",
  };
  return { name, message: map[name] ?? "카메라·마이크를 사용할 수 없습니다." };
}

/**
 * 웹캠·마이크 획득과 미디어 채널 전송 (docs/TRD.md §4.2, §4.3).
 *  - 오디오: AudioContext(16kHz) → AudioWorklet → 16kHz mono PCM16 500ms 청크 → WS 바이너리 프레임(0x01)
 *  - 영상: MediaRecorder(webm/vp8, 640×480, 15fps, 600kbps, 5초 타임슬라이스) → 프레임(0x02)
 * 오디오는 `setSending(true)`(답변 중)일 때만 보낸다 — TTS 재생 중 자기 음성 유입 방지. 청크 seq 는 연결이 바뀌어도 이어서 증가한다.
 */
export function useMediaCapture() {
  const [status, setStatus] = useState<MediaStatus>("idle");
  const [error, setError] = useState<MediaError | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const seqRef = useRef(0);
  const unacked = useRef<{ seq: number; buf: ArrayBuffer }[]>([]);
  const sending = useRef(false);
  const stopped = useRef(false);
  const reconnects = useRef(0);
  const tokenSource = useRef<(() => Promise<string | null>) | null>(null);
  const sessionIdRef = useRef("");

  const sendBuf = useCallback((buf: ArrayBuffer) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(buf);
  }, []);

  /** 성공하면 null, 실패하면 사용자에게 보여줄 오류를 반환한다 (상태 갱신이 비동기라 반환값으로 즉시 판단할 수 있게 함). */
  const acquire = useCallback(async (): Promise<MediaError | null> => {
    setStatus("requesting");
    setError(null);
    stopped.current = false;
    let media: MediaStream;
    try {
      // 사전 점검(APP-06)에서 고른 장치를 쓴다. 그 장치가 사라졌어도 실패하지 않도록 exact 가 아닌 ideal 로 요청한다.
      const pick = readDeviceChoice();
      media = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, ...(pick.audio ? { deviceId: { ideal: pick.audio } } : {}) },
        video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 15 }, ...(pick.video ? { deviceId: { ideal: pick.video } } : {}) },
      });
    } catch (e) {
      const err = describeMediaError(e);
      setError(err);
      setStatus("error");
      return err;
    }
    streamRef.current = media;
    setStream(media);

    try {
      let ctx: AudioContext;
      try { ctx = new AudioContext({ sampleRate: SAMPLE_RATE }); } catch { ctx = new AudioContext(); }
      ctxRef.current = ctx;
      await ctx.audioWorklet.addModule("/audio-worklet-pcm.js");
      const src = ctx.createMediaStreamSource(new MediaStream(media.getAudioTracks()));
      const node = new AudioWorkletNode(ctx, "pcm-capture", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
      const mute = ctx.createGain();
      mute.gain.value = 0;  // 그래프를 구동시키되 스피커로는 내보내지 않는다 (마이크 되울림 방지)
      src.connect(node).connect(mute).connect(ctx.destination);

      const resampler = new LinearResampler(ctx.sampleRate);
      const chunker = new PcmChunker(CHUNK_SAMPLES);
      let lastLevel = 0;
      node.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const mono = resampler.process(ev.data);
        const now = performance.now();
        if (now - lastLevel > LEVEL_INTERVAL_MS) { lastLevel = now; useInterviewStore.getState().patch({ micLevel: rmsLevel(mono) }); }
        if (!sending.current) { chunker.reset(); return; }  // 답변 중이 아닐 때의 소리는 버린다
        for (const chunk of chunker.push(floatToInt16(mono))) {
          const seq = seqRef.current++;
          const buf = buildAudioFrame(seq, chunk);
          unacked.current.push({ seq, buf });
          if (unacked.current.length > UNACKED_MAX) unacked.current.shift();
          sendBuf(buf);
        }
      };
      if (ctx.state === "suspended") await ctx.resume();
    } catch (e) {
      // 오디오 파이프라인을 만들 수 없으면 면접을 진행할 수 없다 (STT 입력이 없음)
      media.getTracks().forEach((t) => t.stop());
      const err = { name: e instanceof Error ? e.name : "AudioError", message: "오디오 처리를 시작할 수 없습니다. 최신 Chrome/Edge 브라우저에서 다시 시도해 주세요." };
      setError(err);
      setStatus("error");
      return err;
    }
    setStatus("ready");
    return null;
  }, [sendBuf]);

  const startRecorder = useCallback(() => {
    const media = streamRef.current;
    if (!media || recorderRef.current || typeof MediaRecorder === "undefined") return;
    const mime = ["video/webm;codecs=vp8", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m));
    if (!mime) return;
    const rec = new MediaRecorder(new MediaStream(media.getVideoTracks()), { mimeType: mime, videoBitsPerSecond: 600_000 });
    rec.ondataavailable = async (ev) => {
      if (ev.data.size === 0) return;
      const data = await ev.data.arrayBuffer();
      sendBuf(buildVideoFrame(seqRef.current++, data));
    };
    rec.start(5000);
    recorderRef.current = rec;
  }, [sendBuf]);

  const openMedia = useCallback((token: string) => {
    const ws = new WebSocket(`${wsBase()}/ws/sessions/${sessionIdRef.current}/media?token=${encodeURIComponent(token)}`);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onopen = () => {
      reconnects.current = 0;
      for (const f of unacked.current) ws.send(f.buf);  // 끊긴 동안 ack 받지 못한 청크 재전송 (서버는 seq 로 중복을 버린다)
      startRecorder();
    };
    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null;
      if (stopped.current) return;
      const delay = backoffMs(++reconnects.current);
      const getToken = tokenSource.current;
      if (delay === null || !getToken) return;
      setTimeout(async () => {
        if (stopped.current || wsRef.current) return;
        const t = await getToken();
        if (t && !stopped.current) openMedia(t);
      }, delay);
    };
  }, [startRecorder]);

  /** control 채널이 연결된 뒤 호출한다 (서버는 control 이 먼저 있어야 media 를 받는다). */
  const connect = useCallback((sessionId: string, token: string, refresh: () => Promise<string | null>) => {
    if (wsRef.current) return;
    sessionIdRef.current = sessionId;
    tokenSource.current = refresh;
    openMedia(token);
  }, [openMedia]);

  const setSending = useCallback((on: boolean) => { sending.current = on; }, []);
  const onAck = useCallback((ackSeq: number) => { unacked.current = unacked.current.filter((f) => f.seq > ackSeq); }, []);

  const stop = useCallback(() => {
    stopped.current = true;
    sending.current = false;
    if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
    recorderRef.current = null;
    wsRef.current?.close(1000);
    wsRef.current = null;
    void ctxRef.current?.close();
    ctxRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setStream(null);
    setStatus("idle");
  }, []);

  useEffect(() => stop, [stop]);

  return { status, error, stream, acquire, connect, setSending, onAck, stop };
}
