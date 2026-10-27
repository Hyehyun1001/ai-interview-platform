"""DB 기반 잡 큐 (TRD §1.1: Redis/Arq 미사용). 같은 DB 를 쓰는 여러 프로세스가 같은 잡을 중복 처리하지 않도록
`UPDATE … WHERE status='queued'` 의 영향 행 수로 선점(compare-and-set)한다 — SQLite/PostgreSQL 모두 동작."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import BackgroundJob, InterviewSession
from app.models.base import utcnow
from app.models.enums import QueueStatus, SessionState

RETRY_BACKOFF_S = (30, 120, 300)
STALE_RUNNING = timedelta(minutes=15)  # 워커가 죽어 running 으로 남은 잡을 되살리는 기준
INTERVIEW_STATES = (SessionState.IN_PROGRESS, SessionState.PAUSED, SessionState.CODING)


@dataclass
class ClaimedJob:
    id: uuid.UUID
    type: str
    payload: dict
    attempts: int


async def interview_active(sm: async_sessionmaker) -> bool:
    """진행 중(또는 일시정지로 슬롯을 점유한) 면접이 있으면 무거운 후처리를 멈춘다 (TRD §1.3, §2.5)."""
    async with sm() as db:
        return (await db.execute(select(InterviewSession.id).where(InterviewSession.state.in_(INTERVIEW_STATES)).limit(1))).first() is not None


async def requeue_stale(sm: async_sessionmaker) -> int:
    async with sm() as db:
        res = await db.execute(update(BackgroundJob).where(BackgroundJob.status == QueueStatus.RUNNING, BackgroundJob.updated_at < utcnow() - STALE_RUNNING)
                               .values(status=QueueStatus.QUEUED))
        await db.commit()
        return res.rowcount or 0


async def claim(sm: async_sessionmaker, job_type: str) -> ClaimedJob | None:
    async with sm() as db:
        row = (await db.execute(select(BackgroundJob).where(BackgroundJob.type == job_type, BackgroundJob.status == QueueStatus.QUEUED,
                                                            BackgroundJob.run_at <= utcnow()).order_by(BackgroundJob.run_at).limit(1))).scalar_one_or_none()
        if row is None:
            return None
        prev_attempts = row.attempts  # bulk UPDATE 가 세션 내 객체도 갱신하므로 갱신 전에 읽어 둔다
        res = await db.execute(update(BackgroundJob).where(BackgroundJob.id == row.id, BackgroundJob.status == QueueStatus.QUEUED)
                               .values(status=QueueStatus.RUNNING, attempts=BackgroundJob.attempts + 1, updated_at=utcnow()))
        await db.commit()
        if res.rowcount != 1:  # 다른 워커가 먼저 가져갔다
            return None
        return ClaimedJob(row.id, row.type, dict(row.payload or {}), prev_attempts + 1)


async def complete(sm: async_sessionmaker, job_id: uuid.UUID) -> None:
    async with sm() as db:
        await db.execute(update(BackgroundJob).where(BackgroundJob.id == job_id).values(status=QueueStatus.DONE))
        await db.commit()


async def fail_or_retry(sm: async_sessionmaker, job: ClaimedJob, max_attempts: int, *, retryable: bool) -> bool:
    """재시도 가능하면 백오프 후 다시 queued, 아니면 failed. 반환: 최종 실패 여부."""
    final = (not retryable) or job.attempts >= max_attempts
    async with sm() as db:
        if final:
            await db.execute(update(BackgroundJob).where(BackgroundJob.id == job.id).values(status=QueueStatus.FAILED))
        else:
            delay = RETRY_BACKOFF_S[min(job.attempts - 1, len(RETRY_BACKOFF_S) - 1)]
            await db.execute(update(BackgroundJob).where(BackgroundJob.id == job.id).values(status=QueueStatus.QUEUED, run_at=utcnow() + timedelta(seconds=delay)))
        await db.commit()
    return final
