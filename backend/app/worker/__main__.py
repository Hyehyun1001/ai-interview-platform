"""리포트 워커 프로세스. 실행: cd backend && python -m app.worker  (환경변수/.env 는 API 와 동일)

API 와 별도 프로세스이므로 같은 DB 를 공유한다. Ollama 는 서버 프로세스라 모델이 중복 로드되지 않는다 (TRD §1.3 주석).
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.ai.guardrail import DbGuardrailEventSink
from app.ai.llm import report_llm_factory
from app.core.config import get_settings
from app.core.crypto import init_crypto
from app.core.database import create_db
from app.worker.runner import ReportWorker


async def main() -> None:
    settings = get_settings()
    init_crypto(settings.data_encryption_key)  # 답변 전사(🔒 암호화 컬럼)를 읽으려면 API 와 같은 키가 필요하다
    engine, sm = create_db(settings.database_url)
    worker = ReportWorker(sm, report_llm_factory(settings), sink=DbGuardrailEventSink(sm), poll_interval_s=settings.report_poll_interval_s,
                          max_attempts=settings.report_max_attempts, llm_timeout_s=settings.report_llm_timeout_s, model_name=settings.ollama_model)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    logging.getLogger("app.worker").info("report worker started model=%s", settings.ollama_model)
    try:
        await worker.run_forever(stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
