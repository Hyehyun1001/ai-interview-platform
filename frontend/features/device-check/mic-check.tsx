"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/primitives";
import { MicDetector, dbToMeter, mediaErrorHint, rmsOfSamples, rmsToDb } from "./device-logic";

/**
 * 마이크 점검 (UI_SPEC §4.5.3). 레벨 미터는 AudioContext + AnalyserNode 를 rAF 로 읽는다.
 * -50dBFS 이상의 입력이 누적 0.5초 이상이면 통과, 5초간 무음이면 안내한다. 소리는 스피커로 내보내지 않고 서버로도 보내지 않는다.
 */
export function MicCheck({ deviceId, active, passed, onPass, onActualDevice, onStreamOpened }: {
  deviceId?: string; active: boolean; passed: boolean; onPass: () => void; onActualDevice: (id: string | undefined) => void; onStreamOpened: () => void;
}) {
  const [level, setLevel] = useState(0);
  const [errName, setErrName] = useState<string | null>(null);
  const [silent, setSilent] = useState(false);
  const [needsGesture, setNeedsGesture] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const ctxRef = useRef<AudioContext | null>(null);
  const cb = useRef({ onPass, onActualDevice, onStreamOpened });
  cb.current = { onPass, onActualDevice, onStreamOpened };

  useEffect(() => {
    if (!active || passed) return;
    let cancelled = false;
    let raf = 0;
    let stream: MediaStream | null = null;
    setErrName(null); setSilent(false); setLevel(0); setNeedsGesture(false);
    void (async () => {
      const audio = (id?: string) => ({ echoCancellation: false, noiseSuppression: false, ...(id ? { deviceId: { exact: id } } : {}) });
      try {
        try { stream = await navigator.mediaDevices.getUserMedia({ audio: audio(deviceId) }); }
        catch (e) {
          if (deviceId && e instanceof DOMException && e.name === "OverconstrainedError") stream = await navigator.mediaDevices.getUserMedia({ audio: audio() });
          else throw e;
        }
      } catch (e) { if (!cancelled) setErrName(e instanceof DOMException ? e.name : "UnknownError"); return; }
      if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
      cb.current.onActualDevice(stream.getAudioTracks()[0]?.getSettings().deviceId);
      cb.current.onStreamOpened();
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const an = ctx.createAnalyser();
      an.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(an);  // destination 에는 연결하지 않는다 (되울림 방지)
      await ctx.resume().catch(() => undefined);
      if (ctx.state !== "running") setNeedsGesture(true);
      const buf = new Float32Array(an.fftSize);
      const det = new MicDetector();
      let prev = performance.now(), lastPaint = 0;
      const loop = (now: number) => {
        if (cancelled) return;
        an.getFloatTimeDomainData(buf);
        const db = rmsToDb(rmsOfSamples(buf));
        const r = det.feed(db, now - prev);
        prev = now;
        if (now - lastPaint > 60) { lastPaint = now; setLevel(dbToMeter(db)); setSilent(r.silent); }
        if (r.passed) { cb.current.onPass(); return; }
        raf = requestAnimationFrame(loop);
      };
      raf = requestAnimationFrame(loop);
    })();
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      void ctxRef.current?.close().catch(() => undefined);
      ctxRef.current = null;
    };
  }, [deviceId, active, passed, attempt]);

  if (!active && !passed) return <p className="text-sm text-muted">카메라 점검을 먼저 완료해 주세요.</p>;
  const pct = passed ? 100 : Math.round(level * 100);
  return (
    <div className="space-y-2" data-testid="mic-check">
      <div role="meter" aria-label="마이크 입력 레벨" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} data-testid="mic-meter" className="h-3 overflow-hidden rounded-full bg-surface-2">
        <div className="h-full bg-primary transition-[width] duration-75" style={{ width: `${pct}%` }} />
      </div>
      {errName ? (
        <div role="alert" className="space-y-2 rounded bg-danger-bg p-3 text-sm text-danger" data-testid="mic-error">
          <p>{mediaErrorHint(errName, "mic")}</p>
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>다시 시도</Button>
        </div>
      ) : passed ? (
        <p role="status" className="text-sm text-success">✅ 음성이 수신되고 있어요</p>
      ) : (
        <>
          <p className="text-sm">&quot;안녕하세요&quot;라고 말해보세요.</p>
          {needsGesture && <Button variant="secondary" onClick={() => void ctxRef.current?.resume().then(() => setNeedsGesture(false))}>소리 감지 시작</Button>}
          {silent && <p role="status" className="text-sm text-warning" data-testid="mic-silent">⚠ 마이크가 음소거되었거나 소리가 작아요.</p>}
        </>
      )}
    </div>
  );
}
