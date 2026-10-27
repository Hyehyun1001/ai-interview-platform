"""면접 세션 수명주기 보조 로직: 사전 준비(인덱싱·사전 검색), warm-up, 종료 처리 (TRD §2.3, §7.4)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.services import Services
from app.models import (Application, BackgroundJob, EvaluationReport, InterviewSession, JobPosting, JobQuestion, ResumeSnapshot)
from app.models.base import utcnow
from app.models.enums import ApplicationStatus, QueueStatus, ReportStatus, SessionState, VectorStatus
from app.schemas.resume import ResumeSchema

log = logging.getLogger("app.sessions")

from app.interview.brain import DEFAULT_MAIN_COUNT  # noqa: E402

# 질문 슬롯별 사전 검색 질의 (TRD §2.3). 담당자가 질문을 직접 등록한 슬롯은 그 질문 텍스트를 질의로 쓴다.
GENERIC_QUERIES = [
    "가장 기억에 남는 프로젝트와 맡은 역할", "사용한 핵심 기술과 선택 이유", "어려웠던 문제를 해결한 경험", "팀 협업과 갈등 해결 경험",
    "성능 개선이나 장애 대응 경험", "자기소개서에 적은 지원 동기", "학습한 내용과 성장 경험", "코드 품질·테스트 경험",
    "설계 결정과 트레이드오프", "입사 후 기여할 수 있는 점",
]


async def prepare_session(svc: Services, sm: async_sessionmaker, session_id: uuid.UUID, main_count: int = DEFAULT_MAIN_COUNT) -> None:
    """이력서·JD 인덱싱 후 슬롯별 검색 결과를 precomputed_context 에 저장한다. 실패해도 면접은 JD 기반 일반 질문으로 가능하다."""
    from app.ai.rag.store import build_precomputed_context, index_resume_snapshot

    async with sm() as db:
        sess = await db.get(InterviewSession, session_id)
        app = await db.get(Application, sess.application_id)
        job = await db.get(JobPosting, app.job_id)
        snap = (await db.execute(select(ResumeSnapshot).where(ResumeSnapshot.application_id == app.id))).scalar_one_or_none()
        manual = (await db.execute(select(JobQuestion).where(JobQuestion.job_id == job.id, JobQuestion.order_no.is_not(None))
                                   .order_by(JobQuestion.order_no))).scalars().all()
        user_id, job_id, snap_id = app.user_id, job.id, snap.id if snap else None
        resume = ResumeSchema.model_validate(snap.data) if snap else None
        jd = (job.requirements, job.preferred, job.duties)
    # 직접 등록한 질문 + 빈 슬롯(일반 질의)로 항상 main_count 개를 맞춘다 (TRD §3.4). 등록 질문이 더 많으면 등록 수를 따른다
    texts = [q.text for q in manual]
    queries = texts + GENERIC_QUERIES[len(texts):main_count]
    status = VectorStatus.FAILED
    slots: list[dict[str, Any]] = [{"slot": i, "query": q, "resume": [], "jd": []} for i, q in enumerate(queries)]
    store = svc.vector_store()
    if store is not None:
        try:
            if resume is not None:
                await index_resume_snapshot(store, str(snap_id), str(app.id), str(user_id), resume, keep_resident=True)
            await asyncio.to_thread(store.index_jd, str(job_id), requirements=jd[0], preferred=jd[1], duties=jd[2])
            slots = await asyncio.to_thread(build_precomputed_context, store, str(snap_id) if snap_id else None, str(job_id), queries)
            status = VectorStatus.INDEXED
        except Exception as e:  # noqa: BLE001  임베딩/Chroma 실패 → 이력서 컨텍스트 없이 진행 (환각 차단)
            log.warning("session prep degraded: %s", type(e).__name__)
        finally:
            store.embedder.unload()  # 면접 중에는 bge-m3 를 쓰지 않는다 (TRD §2.3)
    async with sm() as db:
        sess = await db.get(InterviewSession, session_id)
        sess.precomputed_context = {"slots": slots, "prepared_at": utcnow().isoformat(), "vector_status": status.value}
        if snap_id:
            row = await db.get(ResumeSnapshot, snap_id)
            row.vector_status = status
        await db.commit()


def prep_done(sess: InterviewSession) -> bool:
    return bool(sess.precomputed_context and "prepared_at" in sess.precomputed_context)


async def warm_up(svc: Services, engines: Any, sm: async_sessionmaker, session_id: uuid.UUID) -> None:
    """LLM·STT 를 미리 올린다 (TRD §7.4 start). 실패하면 경량 모드(degraded)로 표시하되 시작은 막지 않는다 (NFR-R5)."""
    degraded = False

    async def llm() -> None:
        # 모델을 메모리에 올리는 것이 목적이므로 아주 짧은 JSON 응답만 요청한다 (콜드 스타트는 수십 초 걸릴 수 있다)
        await asyncio.wait_for(svc.llm_factory(0.0).ainvoke([HumanMessage('JSON 객체 {"ok": true} 만 출력하세요.')]), timeout=120)

    async def stt() -> None:
        w = getattr(engines.stt, "warmup", None)
        if w is not None:
            await w()

    for name, fn in (("llm", llm), ("stt", stt)):
        try:
            await fn()
        except Exception as e:  # noqa: BLE001
            degraded = degraded or name == "llm"
            log.warning("warm-up %s failed: %s", name, type(e).__name__)
    async with sm() as db:
        sess = await db.get(InterviewSession, session_id)
        if sess.state == SessionState.CREATED:
            sess.state = SessionState.READY
        if degraded:
            sess.degraded_mode = True
        await db.commit()
    svc.warmups[session_id] = "done"


async def finalize_session(sm: async_sessionmaker, session_id: uuid.UUID) -> ReportStatus:
    """종료 처리(멱등): 지원 상태 → interview_done, 리포트 행 + 리포트 잡 enqueue."""
    async with sm() as db:
        sess = await db.get(InterviewSession, session_id)
        if sess.state in (SessionState.READY, SessionState.CREATED, SessionState.ABORTED):
            raise ValueError(sess.state.value)
        if sess.state != SessionState.FINISHED:
            sess.state, sess.ended_at = SessionState.FINISHED, sess.ended_at or utcnow()
        app = await db.get(Application, sess.application_id)
        if app.status in (ApplicationStatus.APPLIED, ApplicationStatus.PREPARED, ApplicationStatus.INTERVIEWING):
            app.status = ApplicationStatus.INTERVIEW_DONE
        report = (await db.execute(select(EvaluationReport).where(EvaluationReport.session_id == session_id))).scalar_one_or_none()
        if report is None:
            report = EvaluationReport(session_id=session_id, status=ReportStatus.QUEUED)
            db.add(report)
            db.add(BackgroundJob(type="report", payload={"session_id": str(session_id)}, status=QueueStatus.QUEUED))
        await db.commit()
        return report.status
