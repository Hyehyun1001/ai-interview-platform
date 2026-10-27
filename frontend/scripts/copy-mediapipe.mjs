// MediaPipe WASM 런타임을 public/ 으로 복사한다 — 외부 CDN 금지 (UI_SPEC §3.3, TRD NFR-S2).
// face_landmarker.task 모델 파일은 npm 패키지에 포함되지 않으므로 scripts/fetch-face-model.mjs 로 1회 내려받는다.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "@mediapipe", "tasks-vision", "wasm");
const dst = join(root, "public", "mediapipe", "wasm");
if (!existsSync(src)) {
  console.warn("[copy-mediapipe] @mediapipe/tasks-vision 이 아직 설치되지 않았습니다 — 건너뜀");
  process.exit(0);
}
mkdirSync(dst, { recursive: true });
cpSync(src, dst, { recursive: true });
console.log("[copy-mediapipe] wasm ->", dst);
