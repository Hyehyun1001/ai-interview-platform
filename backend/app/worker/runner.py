"""리포트 워커 루프: 면접 중에는 멈추고(pause), 잡을 하나씩 선점해 처리한다."""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable

from langchain_core.runnables import Runnable
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.errors import LLMUnavailable
from app.ai.guardrail import GuardrailEventSink
from app.worker import queue
from app.worker.report_service import ReportNotPossible, generate_report, mark_report_failed, mark_report_queued

log = logging.getLogger("app.worker")
JOB_TYPE = "report"


class ReportWorker:
    def __init__(self, sm: async_sessionmaker, llm_factory: Callable[[float], Runnable], *, sink: GuardrailEventSink | None = None,
                 poll_interval_s: float = 3.0, max_attempts: int = 3, llm_timeout_s: float = 150.0, model_name: str = ""):
        self.sm, self.llm_factory, self.sink = sm, llm_factory, sink
        self.poll_interval_s, self.max_attempts, self.llm_timeout_s, self.model_name = poll_interval_s, max_attempts, llm_timeout_s, model_name

    async def run_once(self) -> str:
        """잡 1건 처리. 반환: 'paused'(면접 중) | 'idle'(대기 잡 없음) | 'done' | 'retry' | 'failed'."""
        if await queue.interview_active(self.sm):
            return "paused"
        await queue.requeue_stale(self.sm)
        job = await queue.claim(self.sm, JOB_TYPE)
        if job is None:
            return "idle"
        session_id = uuid.UUID(job.payload["session_id"])
        try:
            await generate_report(self.sm, self.llm_factory, session_id, sink=self.sink, timeout_s=self.llm_timeout_s, model_name=self.model_name)
        except LLMUnavailable:  # Ollama 가 꺼져 있거나 느림 — 잠시 후 재시도, 한도를 넘으면 failed
            final = await queue.fail_or_retry(self.sm, job, self.max_attempts, retryable=True)
            await (mark_report_failed if final else mark_report_queued)(self.sm, session_id)
            log.warning("report job %s LLM unavailable attempt=%d final=%s", job.id, job.attempts, final)
            return "failed" if final else "retry"
        except ReportNotPossible as e:  # 채점 가능한 답변이 없음 — 재시도해도 같다
            await queue.fail_or_retry(self.sm, job, self.max_attempts, retryable=False)
            await mark_report_failed(self.sm, session_id)
            log.warning("report job %s not possible: %s", job.id, e)
            return "failed"
        except Exception as e:  # noqa: BLE001  예상 밖 오류: 원문·PII 가 섞일 수 있어 타입만 기록
            final = await queue.fail_or_retry(self.sm, job, self.max_attempts, retryable=True)
            await (mark_report_failed if final else mark_report_queued)(self.sm, session_id)
            log.error("report job %s error=%s final=%s", job.id, type(e).__name__, final)
            return "failed" if final else "retry"
        await queue.complete(self.sm, job.id)
        return "done"

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                outcome = await self.run_once()
            except Exception as e:  # noqa: BLE001  DB 일시 오류 등으로 루프가 죽지 않게 한다
                log.error("worker loop error=%s", type(e).__name__)
                outcome = "idle"
            if outcome in ("done", "retry", "failed"):
                continue  # 대기 잡이 더 있을 수 있으니 바로 다음 잡
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.poll_interval_s)
            except asyncio.TimeoutError:
                pass
