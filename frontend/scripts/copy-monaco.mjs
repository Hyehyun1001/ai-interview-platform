// Monaco Editor(AMD 번들)를 public/ 으로 복사한다 — 기본 설정은 CDN(jsdelivr)에서 내려받으므로 외부 호출 금지 정책에 맞게 로컬로 서빙한다 (UI_SPEC §3.3, NFR-S2).
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "monaco-editor", "min", "vs");
const dst = join(root, "public", "monaco", "vs");
if (!existsSync(src)) {
  console.warn("[copy-monaco] monaco-editor 가 아직 설치되지 않았습니다 — 건너뜀");
  process.exit(0);
}
mkdirSync(dst, { recursive: true });
cpSync(src, dst, { recursive: true });
console.log("[copy-monaco] vs ->", dst);
