"""실제 AI 엔진(Ollama · faster-whisper · macOS say)으로 구동하는 개발 스택. 실제 모델 E2E 용.

  python scripts/dev_real_stack.py [--port 8000] [--dir .devstack-real]

- 새 SQLite DB + 시드(scripts/seed_dev.py) 후 `create_app()` 기본 엔진을 그대로 쓴다.
- 필요: `ollama serve` 실행 중 + OLLAMA_MODEL 설치, faster-whisper 모델 캐시. bge-m3(sentence-transformers) 가 없으면
  이력서 검색 없이 JD/등록 질문으로 진행한다(자동 폴백, TRD §3.3).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("JWT_SECRET", "dev-real-stack-" + "x" * 40)
os.environ.setdefault("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())

import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.rate_limit import SlidingWindowLimiter  # noqa: E402
from app.main import create_app  # noqa: E402
from scripts.seed_dev import seed  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dir", default=str(BACKEND / ".devstack-real"))
    a = ap.parse_args()
    root = Path(a.dir)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    url = f"sqlite+aiosqlite:///{root / 'dev.db'}"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    settings = Settings(_env_file=None, database_url=url, media_root=root / "media", chroma_path=root / "chroma", max_concurrent_sessions=1, report_worker_embedded=True, interview_main_count=3,
                        sandbox_enabled=True,  # 코딩테스트 공고를 쓰려면 샌드박스가 켜져 있어야 한다(도커 이미지: backend/sandbox/build.sh)
                        jwt_secret=os.environ["JWT_SECRET"], data_encryption_key=os.environ["DATA_ENCRYPTION_KEY"])
    app = create_app(settings)  # 기본 엔진: FasterWhisperSTT + LocalSayTTS + ChainBrain(Ollama)
    app.state.register_limiter = SlidingWindowLimiter(max_events=10_000, window_sec=60)
    app.state.login_limiter = SlidingWindowLimiter(max_events=10_000, window_sec=60)
    ids = asyncio.run(seed(url, settings.media_root, demo_admin=True, manual_questions=1, coding_job=True))  # 1개만 직접 등록 → 나머지 2개는 이력서 RAG + LLM 이 생성
    (root / "ids.json").write_text(json.dumps(ids))
    print(f"[real-stack] sandbox={'on' if settings.sandbox_enabled else 'off'} stt={settings.stt_model} llm={settings.ollama_model} tts={settings.tts_provider}:{settings.tts_voice}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
