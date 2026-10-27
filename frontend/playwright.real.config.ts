import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

/**
 * 실제 AI 엔진 E2E (Ollama · faster-whisper · macOS say). 가짜 카메라/마이크 장치를 쓰되 마이크에는 **실제 한국어 음성 파일**을 입력한다.
 * 실제 웹캠·마이크·사람 얼굴은 자동화로 대체할 수 없다: 카메라는 패턴 영상(얼굴 없음)이라 시선 분석은 검증되지 않는다.
 * 사전 조건: `ollama serve` 실행 중, 모델 설치, faster-whisper 모델 캐시. 실행: `npm run test:e2e:real`
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /real\..*spec\.ts/,
  timeout: 15 * 60_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    ...devices["Desktop Chrome"],
    permissions: ["camera", "microphone"],
    launchOptions: {
      args: [
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
        `--use-file-for-fake-audio-capture=${path.resolve(__dirname, "e2e/fixtures/answer-ko.wav")}`,
      ],
    },
  },
  webServer: [
    { command: "cd ../backend && .venv/bin/python scripts/dev_real_stack.py", url: "http://127.0.0.1:8000/openapi.json", reuseExistingServer: false, timeout: 90_000, stdout: "ignore" },
    {
      command: "npm run dev -- -p 3100", url: "http://127.0.0.1:3100/login", reuseExistingServer: true, timeout: 120_000,
      env: { BACKEND_URL: "http://127.0.0.1:8000", NEXT_PUBLIC_WS_URL: "ws://127.0.0.1:8000" },
    },
  ],
});
