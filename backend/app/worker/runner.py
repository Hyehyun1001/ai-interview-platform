"""리포트 워커 루프: 면접 중에는 멈추고(pause), 잡을 하나씩 선점해 처리한다."""
from __future__ import annotations

import asyncio
import contextlib
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
                 poll_interval_s: float = 3.0, max_attempts: int = 3, llm_timeout_s: float = 150.0, model_name: str = "",
                 busy: Callable[[], bool] | None = None, preempt_check_s: float = 1.0):
        self.sm, self.llm_factory, self.sink = sm, llm_factory, sink
        self.busy = busy  # 같은 프로세스가 아는 "면접이 곧 시작된다" 신호(예: warm-up 중). DB 로는 알 수 없는 구간을 메운다
        self.preempt_check_s = preempt_check_s
        self.poll_interval_s, self.max_attempts, self.llm_timeout_s, self.model_name = poll_interval_s, max_attempts, llm_timeout_s, model_name

    async def _should_yield(self) -> bool:
        return (self.busy is not None and self.busy()) or await queue.interview_active(self.sm)

    async def _run_preemptible(self, coro) -> bool:  # noqa: ANN001
        """리포트 생성은 몇 분이 걸리고 Ollama 는 한 번에 하나만 처리한다. 면접이 시작되면 진행 중인 생성을 즉시 취소해(요청이 끊기면 Ollama 가
        생성을 멈춘다) 면접의 LLM 호출이 그 뒤에 줄 서서 타임아웃으로 떨어지지 않게 한다. 반환: 끝까지 실행했는가."""
        task = asyncio.create_task(coro)
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=self.preempt_check_s)
                if done:
                    task.result()  # 예외는 호출자의 처리로 올린다
                    return True
                if await self._should_yield():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    return False
        except asyncio.CancelledError:  # 워커 자체가 종료되는 경우에도 하위 태스크를 남기지 않는다
            task.cancel()
            raise

    async def run_once(self) -> str:
        """잡 1건 처리. 반환: 'paused'(면접 중) | 'preempted'(처리 중 면접이 시작되어 양보) | 'idle'(대기 잡 없음) | 'done' | 'retry' | 'failed'."""
        if await self._should_yield():
            return "paused"
        await queue.requeue_stale(self.sm)
        job = await queue.claim(self.sm, JOB_TYPE)
        if job is None:
            return "idle"
        session_id = uuid.UUID(job.payload["session_id"])
        try:
            finished = await self._run_preemptible(
                generate_report(self.sm, self.llm_factory, session_id, sink=self.sink, timeout_s=self.llm_timeout_s, model_name=self.model_name))
            if not finished:
                await queue.release(self.sm, job.id)
                await mark_report_queued(self.sm, session_id)
                log.info("report job %s preempted by interview", job.id)
                return "preempted"
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
