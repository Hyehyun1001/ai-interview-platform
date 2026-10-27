# Enterprise On-Premise AI Interview Platform

## System Architecture & Constraints
- Platform: Local On-Premise B2B AI Mock Interview Platform
- Target Machine: Mac M2 Pro / 16GB Unified Memory / macOS
- Constraints: 
  - ZERO external SaaS API calls in production logic (Data isolation)[cite: 3, 4].
  - Peak Memory footprint MUST stay under 14.5GB (OS + Browser + Ollama + STT + Web).
  - Max Concurrent Interview Session = 1 (`MAX_CONCURRENT_SESSIONS=1`).

## Source of Truth (Reference Documents)
Before implementing any feature, ALWAYS consult the corresponding spec file in `docs/`:
- **PRD (What/Why):** `docs/PRD.md` (Product Requirements, Personas, Workflows)[cite: 3]
- **TRD (How/Tech):** `docs/TRD.md` (Architecture, DB Schema, APIs, Memory Specs)
- **UI Spec (Frontend):** `docs/UI_SPEC.md` (Next.js App Router, Components, WS Events)

## Tech Stack
- Frontend: Next.js 14 (App Router, TS), Tailwind CSS, TanStack Query v5, Zustand, Recharts[cite: 4, 5]
- Backend: Python 3.11+, FastAPI (Uvicorn), SQLAlchemy 2.0 (Alembic), Pydantic v2
- AI Pipelines: Ollama (Qwen2.5-7B Q4_K_M), faster-whisper (CPU int8), ChromaDB (Embedded), MediaPipe (WASM)
- DB: SQLite (Dev) / PostgreSQL 16 (Prod)

## Decisions from M0 Benchmark (measured 2026-10-26, details: `docs/TRD.md` §9.1, §11)
- **STT:** `faster-whisper large-v3-turbo`, int8 CPU, `cpu_threads=6` (`STT_CPU_THREADS`). Keep it behind the `STTEngine` interface. `mlx-whisper` is a post-M0 optimization backlog item (TRD §11 #25), not implemented.
- **Latency design needs BOTH techniques** — dropping either makes the E2E target unreachable:
  1. Background chunked incremental STT (decode finished speech chunks while the user talks; only the last chunk is decoded at answer end). Whisper pays a fixed ~4s encoder cost per call regardless of input length, and decoding a full 60s answer after it ends takes ~14s.
  2. Parse the streaming LLM JSON and start TTS the moment the `question` field closes. JSON key order MUST be `needed, reason, grounding_keywords, question, evidence` so Guardrail G2 passes before any audio plays.
- **E2E target (FINAL, decided 2026-10-26, TRD §11 #24): p50 <= 9.5s, p95 <= 12s** (answer end -> next question audio; turbo + incremental STT + question-field TTS streaming). Basis: component medians sum to ~8.8-9.3s (incremental STT tail 4.34s + follow-up question to TTS start 3.6-4.1s + TTS 0.88s); the question comes after `grounding_keywords` so G2 can run before any audio plays. Margin is only 0.2-0.7s and p95 (component sum ~10-13s) overlaps the 12s limit, so it is NOT verified — confirm with the V-3 100-run measurement once all components are wired. The 4.58s figure belongs to the `small` model — never quote it for turbo.
- Never state latency/memory numbers without data: re-run `backend/.venv/bin/python backend/tests/benchmark_ai.py` (needs `ollama serve`, see script docstring). Results land in `data/benchmarks/` (gitignored).
- `stt_partial` (live caption) cannot keep a 2s cadence on CPU turbo — treat it as best-effort in UI.

## Conventions Fixed in Phase 2 (details: `docs/TRD.md` §3.1, §3.5, §4.1, §7.7)
- **Guardrail:** retry only content failures (schema/G2-G6); LLM connection loss raises `LLMUnavailable` (no retry). After 3 failures the follow-up is SKIPPED (main question -> unused bank candidate -> generic). Event logs store fixed reason strings only — never user text.
- **Streaming follow-up:** once TTS has started the attempt is never retried (no double narration); later JSON/evidence failures only drop the evidence.
- **WS:** server-assigned envelope `seq`; media ack uses `ack_seq` (never reuse `seq` in a payload). Handshake errors close with 4400/4401/4403/4404/4408/4409. Reconnect = server auto-resends current state; client `resume` is optional. Open control before media. Media `seq` continues for the whole connection.
- **Cleanup that must survive handler cancellation** (pause/expiry on disconnect) runs in its own task (`SessionRuntime._spawn`), not inside the WebSocket handler.
- **Prompt safety:** user text goes inside `<untrusted>` and is `defang`ed. PDF parsing runs in a subprocess.
- **Tests:** `cd backend && .venv/bin/python -m pytest` (no models needed; fakes in `tests/fakes.py`). When changing guardrail/runtime logic, check tests still FAIL when the logic is broken (mutation check) — a green suite alone is not evidence.

## Universal Coding Rules
1. **No Spec Deviation:** Never invent new API endpoints or DB columns without checking `TRD.md` and `UI_SPEC.md` first[cite: 4, 5].
2. **Type Safety & Guardrails:**
   - Backend: All LLM outputs MUST go through Pydantic parser & Guardrail validation (`ai/guardrail.py`).
   - Frontend: All API calls MUST use types generated from Backend OpenAPI (`types/api.ts`).
3. **Data Security (NFR-S1/S2):** Never log PII, raw audio, or raw transcripts to stdout/files.

## Common Commands
- Backend setup: `python3.11 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements-dev.txt` (copy `backend/.env.example` to `backend/.env` and fill `JWT_SECRET`, `DATA_ENCRYPTION_KEY`; startup is refused without them)
- Backend tests: `cd backend && .venv/bin/python -m pytest` (each test builds a temp SQLite DB through Alembic, so migrations are tested too)
- PostgreSQL 16 (prod DB): `cp .env.example .env` (set `POSTGRES_PASSWORD`) → `docker compose up -d postgres` → `cd backend && DATABASE_URL=postgresql+asyncpg://interview:<pw>@127.0.0.1:5432/interview alembic upgrade head`. Run the whole backend suite on it with `TEST_DATABASE_URL=postgresql+asyncpg://interview:<pw>@127.0.0.1:5432/postgres pytest` (a throwaway DB per test, dropped afterwards). Only the DB runs in Docker; backend/frontend/Ollama run on the host (MPS/Metal).
- Coding-test sandbox: `backend/sandbox/build.sh` (pre-builds `sandbox-{python,node,java}:1`; needs network once), then `SANDBOX_ENABLED=true`. Docker-backed tests (`tests/test_sandbox_docker.py`) skip themselves when the images are missing. The Playwright fake stack uses the real sandbox when the images exist.
- Benchmark (TRD V-1/V-2/V-3): `backend/.venv/bin/python backend/tests/benchmark_ai.py --selftest` (no models), full run per script docstring
- Run Dev Backend: `cd backend && uvicorn app.main:app --reload`
- Run Dev Frontend: `cd frontend && npm run dev`
- DB Migration: `cd backend && alembic revision --autogenerate -m "msg"` -> `alembic upgrade head`
- Regenerate Frontend Types: `npx openapi-typescript http://localhost:8000/openapi.json -o frontend/types/api.ts`
- Frontend setup: `cd frontend && npm install` (postinstall copies the MediaPipe WASM and downloads the face model into `public/mediapipe/`, which is gitignored)
- Frontend checks: `cd frontend && npm run typecheck && npm run lint && npm test && npm run build`
- Frontend E2E (fake camera/mic + fake engines): `cd frontend && npx playwright test` (Playwright starts `backend/scripts/dev_fake_stack.py` itself and re-seeds a fresh DB every run)
- Real-engine E2E (Ollama + faster-whisper + say; needs `ollama serve`): `cd frontend && npm run test:e2e:real` (mic = real Korean speech file; camera is a pattern, so gaze detection is NOT exercised)
- Seed dev data: `cd backend && .venv/bin/python scripts/seed_dev.py [--demo-admin]` (no job-authoring API yet)
- Admin/media/session REST is implemented (TRD §7.8.5). Report worker: `cd backend && .venv/bin/python -m app.worker` (or `REPORT_WORKER_EMBEDDED=true`); it pauses during interviews. Job wizard, compare, decision/mail and applicant report are implemented. The whole applicant journey is implemented in the UI: signup modal, APP-01b welcome popup, APP-02/03 jobs + consent, APP-04 mypage (`frontend/features/{auth,jobs,resume,mypage,device-check}`), APP-05 resume step, APP-06 device check -> start, APP-07 coding tab (`features/coding`, Monaco served locally from `public/monaco`). Admin: job templates/preview, internal notes. Coding test: built-in problem bank (`backend/app/coding/problems.py`), Docker sandbox (`SANDBOX_ENABLED=true` + `backend/sandbox/build.sh` first), text code follow-ups over the control WS (TRD §5, §7.8.5 Phase 7). Admin screens ADM-04/04b/07/08 (applicant lists, calendar, notifications/job history) are implemented. Not implemented: password reset, token revocation on password change, per-job coding problem authoring, mypage calendar tab, deadline-D-1 notifications / auto schedules.
- Embeddings: `pip install -r backend/requirements-ai.txt` (sentence-transformers + BAAI/bge-m3, ~2.2GB first download); without it resume retrieval is skipped (`vector_status=failed`) and interviews use JD/generic questions.
