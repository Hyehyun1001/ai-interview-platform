"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/primitives";
import { GazeCalibrator, irisRatios, matrixToYawPitch, type GazeSample } from "@/features/interview/gaze-logic";
import { loadFaceLandmarker } from "@/features/interview/face-landmarker";
import { mediaErrorHint, saveGazeBase } from "./device-logic";

type Face = "checking" | "ok" | "none" | "multi" | "unavailable";
const FACE_TEXT: Record<Face, string> = {
  checking: "얼굴을 찾고 있어요…", ok: "✅ 얼굴이 잘 보입니다", none: "⚠ 얼굴이 화면 중앙에 오도록 조정해 주세요",
  multi: "⚠ 한 명만 화면에 나오도록 해 주세요", unavailable: "얼굴 인식을 사용할 수 없어요 (진행은 가능합니다)",
};

/**
 * 카메라 점검 (UI_SPEC §4.5.3). 통과 조건: 스트림 획득 + 영상 프레임 수신. 얼굴 검출·정면 보정은 보조(P-Mid)이며 실패해도 진행할 수 있다.
 * 영상은 이 브라우저 안에서만 쓰이고 서버로 보내지 않는다.
 */
export function CameraCheck({ sessionId, deviceId, onPass, onActualDevice, onStreamOpened }: {
  sessionId: string; deviceId?: string; onPass: () => void; onActualDevice: (id: string | undefined) => void; onStreamOpened: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [errName, setErrName] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [frameOk, setFrameOk] = useState(false);
  const [face, setFace] = useState<Face>("checking");
  const [calibrated, setCalibrated] = useState(false);
  const cb = useRef({ onPass, onActualDevice, onStreamOpened });
  cb.current = { onPass, onActualDevice, onStreamOpened };

  // 스트림 획득 (장치가 바뀌면 다시 획득)
  useEffect(() => {
    let cancelled = false;
    let stream: MediaStream | null = null;
    setErrName(null); setFrameOk(false); setFace("checking"); setCalibrated(false);
    const video = (id?: string) => ({ width: { ideal: 640 }, height: { ideal: 480 }, ...(id ? { deviceId: { exact: id } } : {}) });
    void (async () => {
      try {
        try { stream = await navigator.mediaDevices.getUserMedia({ video: video(deviceId) }); }
        catch (e) {
          if (deviceId && e instanceof DOMException && e.name === "OverconstrainedError") stream = await navigator.mediaDevices.getUserMedia({ video: video() });  // 저장된 장치가 사라졌다
          else throw e;
        }
      } catch (e) { if (!cancelled) setErrName(e instanceof DOMException ? e.name : "UnknownError"); return; }
      if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
      const v = videoRef.current;
      if (!v) return;
      v.srcObject = stream;
      cb.current.onActualDevice(stream.getVideoTracks()[0]?.getSettings().deviceId);
      cb.current.onStreamOpened();
      const got = () => { if (!cancelled && v.videoWidth > 0) { setFrameOk(true); cb.current.onPass(); } };
      if (typeof v.requestVideoFrameCallback === "function") v.requestVideoFrameCallback(got);
      else v.addEventListener("loadeddata", got, { once: true });
      void v.play().catch(() => undefined);
    })();
    return () => { cancelled = true; stream?.getTracks().forEach((t) => t.stop()); if (videoRef.current) videoRef.current.srcObject = null; };
  }, [deviceId, attempt]);

  // 얼굴 검출 + 정면 2초 보정 (보조 기능: 모델을 못 불러와도 점검은 계속된다)
  useEffect(() => {
    if (!frameOk) return;
    const v = videoRef.current;
    if (!v) return;
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    let lm: Awaited<ReturnType<typeof loadFaceLandmarker>> | null = null;
    const cal = new GazeCalibrator();
    let done = false, last = -1;
    loadFaceLandmarker().then((m) => {
      if (cancelled) { m.close(); return; }
      lm = m;
      timer = setInterval(() => {
        if (v.readyState < 2 || v.currentTime === last) return;
        last = v.currentTime;
        const t = performance.now();
        const res = lm!.detectForVideo(v, t);
        const n = res.faceLandmarks.length;
        setFace(n === 0 ? "none" : n > 1 ? "multi" : "ok");
        if (done) return;
        const sample: GazeSample = { t, faces: n };
        if (n === 1) {
          const mtx = res.facialTransformationMatrixes[0]?.data;
          const iris = irisRatios(res.faceLandmarks[0]);
          if (mtx && iris) Object.assign(sample, matrixToYawPitch(mtx), iris);
        }
        const base = cal.add(sample);
        if (base) { done = true; saveGazeBase(sessionId, base); setCalibrated(true); }
      }, 150);
    }).catch(() => { if (!cancelled) setFace("unavailable"); });
    return () => { cancelled = true; if (timer) clearInterval(timer); lm?.close(); };
  }, [frameOk, sessionId, deviceId, attempt]);

  return (
    <div className="space-y-2">
      <div className="relative aspect-[4/3] overflow-hidden rounded-lg bg-black" data-testid="camera-preview">
        <video ref={videoRef} muted playsInline autoPlay className="h-full w-full -scale-x-100 object-cover" aria-label="카메라 미리보기" />
        <div aria-hidden className="pointer-events-none absolute inset-[18%] rounded-[40%] border-2 border-dashed border-white/60" />
      </div>
      {errName ? (
        <div role="alert" className="space-y-2 rounded bg-danger-bg p-3 text-sm text-danger" data-testid="camera-error">
          <p>{mediaErrorHint(errName, "camera")}</p>
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>다시 시도</Button>
        </div>
      ) : (
        <>
          <p role="status" className="text-sm" data-testid="face-status">{frameOk ? FACE_TEXT[face] : "카메라를 켜는 중…"}</p>
          <p className="text-xs text-muted" data-testid="calibration-status">
            {calibrated ? "정면 보정 완료" : "시선 이탈 감지를 위해 정면을 2초간 바라봐 주세요 (얼굴이 인식되면 자동 진행)"}
          </p>
        </>
      )}
    </div>
  );
}
