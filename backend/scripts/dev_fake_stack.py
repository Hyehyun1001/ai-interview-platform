"""프런트엔드 개발·E2E 용 가짜 엔진 스택 (실제 모델 없이 면접 흐름 전체를 구동한다).

  python scripts/dev_fake_stack.py [--port 8000] [--dir .devstack]

- 임시 SQLite 에 Alembic 으로 스키마를 만들고 scripts/seed_dev.py 로 시드한다 (applicant@corp.local / hr@corp.local, 비밀번호 Passw0rd!, 면접 완료 지원자 2명 포함).
- 지원 → 이력서 → 세션 → 장치 점검 → 시작은 **실제 REST API** 를 쓴다 (E2E 가 호출). 세션은 미리 만들지 않는다.
- STT/TTS/두뇌는 tests/fakes.py 의 가짜를 쓴다. TTS 는 브라우저가 재생할 수 있는 짧은 톤 WAV 를 돌려준다.
- 시드 ID 는 <dir>/ids.json 에 기록한다.
**개발 전용**: 운영 코드 경로가 아니며, 실제 STT/LLM 품질이나 지연은 이 스택으로 검증할 수 없다.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import os
import shutil
import struct
import sys
import wave
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("JWT_SECRET", "dev-fake-stack-" + "x" * 40)
os.environ.setdefault("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())

import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.interview.media_store import MediaStore  # noqa: E402
from app.interview.runtime import Engines, Tuning  # noqa: E402
from app.main import create_app  # noqa: E402
from app.schemas.ai import FollowupDecision  # noqa: E402
from tests.fakes import FakeBrain, FakeSTT  # noqa: E402
from scripts.seed_dev import seed  # noqa: E402
from app.ai.rag.store import VectorStore, create_chroma_client  # noqa: E402
from app.core.rate_limit import SlidingWindowLimiter  # noqa: E402
from app.core.services import Services  # noqa: E402
from tests.fakes import HashEmbedder, ScriptedFactory  # noqa: E402


def tone_wav(seconds: float = 1.2, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(2500 * math.sin(2 * math.pi * 330 * i / rate))) for i in range(int(rate * seconds))))
    return buf.getvalue()


class ToneTTS:
    format = "wav"

    def __init__(self) -> None:
        self.wav = tone_wav()

    async def synthesize(self, text: str):  # noqa: ANN201
        half = len(self.wav) // 2
        yield self.wav[:half]
        yield self.wav[half:]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dir", default=str(BACKEND / ".devstack"))
    ap.add_argument("--total-main", type=int, default=2)
    a = ap.parse_args()

    root = Path(a.dir)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    url = f"sqlite+aiosqlite:///{root / 'dev.db'}"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")

    settings = Settings(_env_file=None, database_url=url, media_root=root / "media", max_concurrent_sessions=1,
                        jwt_secret=os.environ["JWT_SECRET"], data_encryption_key=os.environ["DATA_ENCRYPTION_KEY"])
    followup = FollowupDecision(needed=True, reason="ambiguous", grounding_keywords=["Redis"],
                                question="Redis 캐시 무효화는 어떻게 처리하셨나요?", evidence=[])
    brain = FakeBrain(total_main=a.total_main, followups=[followup], max_followups=1, answer_limit=60)
    engines = Engines(stt=FakeSTT(), tts=ToneTTS(), brain=brain, media=MediaStore(settings.media_root),
                      tuning=Tuning(countdown_step_s=0.5, answer_start_grace_s=30.0))
    store = VectorStore(create_chroma_client(None), HashEmbedder())  # 임베딩도 가짜 (bge-m3 미사용)
    class RecordingMailer:  # E2E: 실제 SMTP 대신 발송 내역만 파일에 남긴다 (수신자·제목만, 본문 제외)
        async def send(self, to: str, subject: str, body: str) -> None:
            (root / "mail.log").open("a").write(f"{to}\t{subject}\n")

    services = Services(llm_factory=ScriptedFactory(default="{}"), vector_store_factory=lambda: store, mailer=RecordingMailer())
    app = create_app(settings, engines, services)  # init_crypto 가 여기서 호출되므로 시드보다 먼저 만든다
    app.state.login_limiter = SlidingWindowLimiter(max_events=10_000, window_sec=60)  # E2E 는 같은 계정으로 자주 로그인한다 (운영 한도는 5회/분)
    ids = asyncio.run(seed(url, settings.media_root, demo_admin=True))
    (root / "ids.json").write_text(json.dumps(ids))
    print(f"[dev-stack] {ids}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
