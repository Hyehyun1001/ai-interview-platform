// MediaPipe Face Landmarker 모델을 개발 시점에 한 번만 내려받아 public/mediapipe/ 에 둔다 (런타임 외부 호출 없음).
// 온프레미스 배포에서는 이 파일을 사전 번들로 반입한다 (TRD §8.1 모델 사전 다운로드).
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "mediapipe", "face_landmarker.task");

if (existsSync(out) && statSync(out).size > 1_000_000) {
  console.log("[fetch-face-model] 이미 있음:", out, `(${statSync(out).size} bytes)`);
  process.exit(0);
}
mkdirSync(dirname(out), { recursive: true });
const res = await fetch(URL);
if (!res.ok) throw new Error(`다운로드 실패 HTTP ${res.status}`);
const buf = Buffer.from(await res.arrayBuffer());
if (buf.length < 1_000_000) throw new Error(`파일이 너무 작습니다 (${buf.length} bytes)`);
writeFileSync(out, buf);
console.log("[fetch-face-model] 저장:", out, `(${buf.length} bytes) sha256=${createHash("sha256").update(buf).digest("hex")}`);
