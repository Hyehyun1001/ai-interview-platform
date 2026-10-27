import type { FaceLandmarker } from "@mediapipe/tasks-vision";

/** MediaPipe Face Landmarker 로드 (WASM·모델은 /mediapipe/ 에서 자체 호스팅 — 영상이 밖으로 나가지 않는다). 시선 추적과 사전 점검이 함께 쓴다. */
export async function loadFaceLandmarker(): Promise<FaceLandmarker> {
  const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision");
  const fileset = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
  const make = (delegate: "GPU" | "CPU") => FaceLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: "/mediapipe/face_landmarker.task", delegate },
    runningMode: "VIDEO", numFaces: 2, outputFacialTransformationMatrixes: true,
  });
  try { return await make("GPU"); } catch { return await make("CPU"); }  // GPU 델리게이트가 없는 환경 대비
}
