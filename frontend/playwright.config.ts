import { defineConfig, devices } from "@playwright/test";

/**
 * E2E: Chromium 가짜 미디어 장치 + 백엔드 가짜 엔진 스택(backend/scripts/dev_fake_stack.py).
 * 백엔드 스택은 실행할 때마다 DB 를 새로 시드하므로(reuseExistingServer: false) 테스트를 몇 번이든 다시 돌릴 수 있다.
 * 가짜 엔진이라 STT/LLM 품질·지연은 검증하지 못한다 — 실제 모델 검증은 e2e-real 프로젝트(npm run test:e2e:real) 참고.
 */
export default defineConfig({
  testDir: "./e2e",
  testIgnore: /real\..*spec\.ts/,
  timeout: 90_000,
  workers: 1,  // 동시 면접 한도(1)와 공유 시드 세션 때문에 직렬 실행
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    ...devices["Desktop Chrome"],
    permissions: ["camera", "microphone"],
    launchOptions: {
      args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
    },
  },
  webServer: [
    {
      command: "cd ../backend && .venv/bin/python scripts/dev_fake_stack.py", url: "http://127.0.0.1:8000/openapi.json",
      reuseExistingServer: false, timeout: 60_000, stdout: "ignore",
    },
    {
      command: "npm run dev -- -p 3100", url: "http://127.0.0.1:3100/login", reuseExistingServer: true, timeout: 120_000,
      env: { BACKEND_URL: "http://127.0.0.1:8000", NEXT_PUBLIC_WS_URL: "ws://127.0.0.1:8000" },
    },
  ],
});
