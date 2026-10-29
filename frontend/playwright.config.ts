import { defineConfig, devices } from "@playwright/test";

/**
 * E2E: Chromium 가짜 미디어 장치 + 백엔드 가짜 엔진 스택(backend/scripts/dev_fake_stack.py).
 * 백엔드 스택은 실행할 때마다 DB 를 새로 시드하므로(reuseExistingServer: false) 테스트를 몇 번이든 다시 돌릴 수 있다.
 * 가짜 엔진이라 STT/LLM 품질·지연은 검증하지 못한다 — 실제 모델 검증은 e2e-real 프로젝트(npm run test:e2e:real) 참고.
 */
// 사용자가 같은 포트로 개발 서버를 띄워 둔 경우를 위해 포트를 환경변수로 바꿀 수 있다 (기본: 백엔드 8000, 프론트 3100).
const API_PORT = process.env.E2E_API_PORT ?? "8000";
const WEB_PORT = process.env.E2E_WEB_PORT ?? "3100";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: /real\..*spec\.ts/,
  timeout: 90_000,
  workers: 1,  // 동시 면접 한도(1)와 공유 시드 세션 때문에 직렬 실행
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    ...devices["Desktop Chrome"],
    permissions: ["camera", "microphone"],
    launchOptions: {
      args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
    },
  },
  webServer: [
    {
      command: `cd ../backend && .venv/bin/python scripts/dev_fake_stack.py --port ${API_PORT}`, url: `http://127.0.0.1:${API_PORT}/openapi.json`,
      reuseExistingServer: false, timeout: 60_000, stdout: "ignore",
    },
    {
      command: `npm run dev -- -p ${WEB_PORT}`, url: `http://127.0.0.1:${WEB_PORT}/login`, reuseExistingServer: true, timeout: 120_000,
      env: { NEXT_DIST_DIR: process.env.E2E_WEB_PORT ? `.next-e2e-${WEB_PORT}` : ".next", BACKEND_URL: `http://127.0.0.1:${API_PORT}`, NEXT_PUBLIC_WS_URL: `ws://127.0.0.1:${API_PORT}`, NEXT_PUBLIC_AUTOSAVE_MS: process.env.E2E_AUTOSAVE_MS ?? "1500" },
    },
  ],
});
