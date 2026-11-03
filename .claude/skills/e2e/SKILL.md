---
name: e2e
description: 프론트엔드 Playwright E2E를 실행한다 (가짜 엔진 기본, 실제 엔진 선택).
---
1. 기본(가짜 카메라·마이크 + fake 엔진): `cd frontend && npx playwright test`
   - 포트 충돌 시: `E2E_API_PORT=8100 E2E_WEB_PORT=3101 npx playwright test`
2. 실제 엔진(Ollama + faster-whisper + say, `ollama serve` 필요): `cd frontend && npm run test:e2e:real`
3. 개발 서버가 떠 있을 때는 `npm run build` 를 실행하지 않는다(.next 가 교체됨).
4. 실패한 시나리오 이름과 원인을 요약해 보고한다.
