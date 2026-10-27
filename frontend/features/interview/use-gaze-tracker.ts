"use client";
import type { FaceLandmarker } from "@mediapipe/tasks-vision";
import { useEffect, useRef } from "react";
import { GAZE, GazeCalibrator, GazeDetector, irisRatios, matrixToYawPitch, type GazeBase, type GazeEvent, type GazeSample } from "./gaze-logic";
import { loadFaceLandmarker } from "./face-landmarker";
import { useInterviewStore } from "./store";

const TICK_MS = 100;  // 10fps 샘플링 (TRD §4.4)

interface Options {
  video: HTMLVideoElement | null;
  /** 웹캠 스트림이 준비되어 모델을 로드·보정해도 되는가 */
  enabled: boolean;
  /** 답변 중일 때만 이벤트를 만든다 (시간 기준: 답변 시작) */
  active: boolean;
  onEvent: (e: GazeEvent) => void;
  /** 사전 환경 점검(APP-06)에서 저장한 정면 기준값. 없으면 면접 시작 후 2초 보정한다. */
  initialBase?: GazeBase | null;
}

/**
 * 시선 이탈 감지 (docs/TRD.md §4.4). MediaPipe Face Landmarker 를 브라우저 WASM 으로 실행하므로 영상이 서버/외부로 나가지 않는다.
 * WASM·모델은 /mediapipe/ 에서 자체 호스팅한다. 모델 로드에 실패해도 면접은 계속된다(시선 분석은 선택 기능, P-Mid).
 * 판정 규칙은 순수 로직 gaze-logic.ts 가 담당한다.
 */
export function useGazeTracker({ video, enabled, active, onEvent, initialBase }: Options): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const activeRef = useRef(active);
  activeRef.current = active;
  const initialBaseRef = useRef(initialBase);
  initialBaseRef.current = initialBase;

  useEffect(() => {
    if (!enabled || !video) return;
    let cancelled = false;
    let landmarker: FaceLandmarker | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    const calibrator = new GazeCalibrator();
    let base: GazeBase | null = initialBaseRef.current ?? null;  // 사전 점검에서 보정해 둔 값이 있으면 곧바로 쓴다
    let detector: GazeDetector | null = null;
    let lastVideoTime = -1;
    const store = useInterviewStore.getState();

    void loadFaceLandmarker().then((lm) => {
      if (cancelled) { lm.close(); return; }
      landmarker = lm;
      timer = setInterval(tick, TICK_MS);
    }).catch((e: unknown) => {
      console.info("[gaze] 시선 분석을 사용할 수 없어 건너뜁니다:", e instanceof Error ? e.message : e);
      store.patch({ gazeStatus: "unknown" });
    });

    function tick() {
      if (!landmarker || video!.readyState < 2 || video!.currentTime === lastVideoTime) return;
      lastVideoTime = video!.currentTime;
      const t = performance.now();
      const res = landmarker.detectForVideo(video!, t);
      const faces = res.faceLandmarks.length;
      const sample: GazeSample = { t, faces };
      if (faces === 1) {
        const m = res.facialTransformationMatrixes[0]?.data;
        const iris = irisRatios(res.faceLandmarks[0]);
        if (m && iris) Object.assign(sample, matrixToYawPitch(m), iris);
      }

      if (!base) {  // 보정: 정면 응시 2초 (질문을 듣는 동안 자연스럽게 수행)
        base = calibrator.add(sample);
        useInterviewStore.getState().patch({ gazeStatus: faces === 0 ? "lost" : "unknown" });
        return;
      }
      // 즉시 로컬 표시용 상태 (확정 전에도 점 색이 바뀐다, ≤0.3s)
      const away = faces > 1 || (faces === 1 && sample.yaw !== undefined && (
        Math.abs(sample.yaw - base.yaw) > GAZE.yawDeg || Math.abs((sample.pitch ?? base.pitch) - base.pitch) > GAZE.pitchDeg ||
        Math.max(Math.abs((sample.irisX ?? base.irisX) - base.irisX), Math.abs((sample.irisY ?? base.irisY) - base.irisY)) > GAZE.irisDev));
      useInterviewStore.getState().patch({ gazeStatus: faces === 0 ? "lost" : away ? "away" : "ok" });

      if (activeRef.current) {
        detector ??= new GazeDetector(base, (e) => onEventRef.current(e), t);
        detector.feed(sample);
      } else if (detector) {
        detector.flush();  // 답변 종료: 진행 중이던 이탈의 남은 구간을 보낸다
        detector = null;
      }
    }

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      detector?.flush();
      landmarker?.close();
      useInterviewStore.getState().patch({ gazeStatus: "unknown" });
    };
  }, [enabled, video]);
}
