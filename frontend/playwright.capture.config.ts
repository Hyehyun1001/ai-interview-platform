import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/** README 용 화면 캡처 전용 설정: `E2E_API_PORT=8100 E2E_WEB_PORT=3101 npx playwright test -c playwright.capture.config.ts` (가짜 엔진 스택 + 시드 데이터). */
export default defineConfig({
  ...base,
  testDir: "./scripts/capture",
  testMatch: /screenshots\.capture\.ts/,
  testIgnore: undefined,
  timeout: 240_000,
  use: { ...base.use, viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: "ko-KR" },
});
