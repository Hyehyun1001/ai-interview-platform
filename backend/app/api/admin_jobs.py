"""공고 작성 마법사 REST (TRD §7.6): 생성·수정·질문 세트·가중치·꼬리질문 규칙·질문 뱅크·게시·마감. 모두 company_id 스코프."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.errors import GuardrailError, LLMUnavailable
from app.ai.guardrail import check_forbidden
from app.api.admin import UNREVIEWED, Staff, company_of
from app.core.deps import get_db
from app.core.errors import ApiError
from app.core.services import Services
from app.models import Application, EvalWeight, FollowupRule, JobHistory, JobPosting, JobQuestion, User
from app.models.base import utcnow
from app.models.enums import ApplicationStatus, JobStatus, QuestionBankStatus, QuestionSource
from app.schemas.admin_jobs import (BankOut, FollowupRulesPut, JobListItem, JobListOut, JobOut, JobWrite, QuestionOut, QuestionsPut, Weights,
                                    WeightsOut, WeightsPut)
from app.worker import scoring

router = APIRouter(prefix="/admin", tags=["admin-jobs"])
POOL_MIN = 10
WEIGHT_KEYS = ("concept_understanding", "logic", "delivery", "attitude", "job_expertise", "code_quality")


async def _job(db: AsyncSession, job_id: uuid.UUID, user: User, *, editable: bool = False) -> JobPosting:
    job = (await db.execute(select(JobPosting).where(JobPosting.id == job_id, JobPosting.company_id == company_of(user),
                                                     JobPosting.status != JobStatus.DELETED))).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "NOT_FOUND", "공고를 찾을 수 없습니다")
    if editable and job.status == JobStatus.CLOSED:
        raise ApiError(409, "JOB_CLOSED", "마감된 공고는 수정할 수 없습니다")
    return job


def _q(q: JobQuestion) -> QuestionOut:
    return QuestionOut(id=q.id, order_no=q.order_no, text=q.text, category=q.category, time_limit_sec=q.time_limit_sec)


async def _ensure_settings(db: AsyncSession, job: JobPosting) -> tuple[EvalWeight, FollowupRule]:
    """가중치·꼬리질문 규칙 행이 없는 공고(API 밖에서 만든 데이터)도 기본값으로 채워 항상 읽고 쓸 수 있게 한다."""
    w = (await db.execute(select(EvalWeight).where(EvalWeight.job_id == job.id))).scalar_one_or_none()
    f = (await db.execute(select(FollowupRule).where(FollowupRule.job_id == job.id))).scalar_one_or_none()
    if w is None:
        w = EvalWeight(job_id=job.id)
        db.add(w)
    if f is None:
        f = FollowupRule(job_id=job.id)
        db.add(f)
    if w.id is None or f.id is None:
        await db.flush()
    return w, f


async def _full(db: AsyncSession, job: JobPosting) -> JobOut:
    w, f = await _ensure_settings(db, job)
    qs = (await db.execute(select(JobQuestion).where(JobQuestion.job_id == job.id))).scalars().all()
    applicants = (await db.execute(select(func.count()).select_from(Application).where(Application.job_id == job.id))).scalar_one()
    manual = sorted((q for q in qs if q.order_no is not None), key=lambda q: q.order_no or 0)
    return JobOut(
        id=job.id, status=job.status, title=job.title, job_category=job.job_category, industry=job.industry, headcount=job.headcount,
        deadline_at=job.deadline_at, duties=job.duties, requirements=job.requirements, preferred=job.preferred, contact_email=job.contact_email,
        answer_time_limit_sec=job.answer_time_limit_sec, coding_test_enabled=job.coding_test_enabled,
        coding_test_time_limit_sec=job.coding_test_time_limit_sec, updated_at=job.updated_at,
        weights=WeightsOut(weights=Weights(**{k: getattr(w, k) for k in WEIGHT_KEYS}), gaze_penalty_enabled=w.gaze_penalty_enabled,
                           cutoff_score=float(job.cutoff_score) if job.cutoff_score is not None else None, cutoff_margin=float(job.cutoff_margin)),
        followup_rules=FollowupRulesPut(max_followups=f.max_followups, trigger_ambiguous=f.trigger_ambiguous, trigger_contradiction=f.trigger_contradiction,
                                        trigger_stt_unclear=f.trigger_stt_unclear, guardrail_strict=f.guardrail_strict),
        questions=[_q(q) for q in manual], question_bank_status=job.question_bank_status,
        bank_count=sum(1 for q in qs if q.order_no is None and q.source == QuestionSource.AI_BANK), applicant_count=applicants)


def _audit(db: AsyncSession, user: User, job_id: uuid.UUID, action: str) -> None:
    db.add(JobHistory(job_id=job_id, action=action, actor_id=user.id))


@router.get("/jobs", response_model=JobListOut)
async def list_jobs(status: JobStatus | None = None, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), user: User = Depends(Staff),
                    db: AsyncSession = Depends(get_db)) -> JobListOut:
    cond = [JobPosting.company_id == company_of(user), JobPosting.status != JobStatus.DELETED]
    if status:
        cond.append(JobPosting.status == status)
    total = (await db.execute(select(func.count()).select_from(JobPosting).where(*cond))).scalar_one()
    jobs = (await db.execute(select(JobPosting).where(*cond).order_by(JobPosting.updated_at.desc()).offset((page - 1) * limit).limit(limit))).scalars().all()
    items = []
    for j in jobs:
        n = (await db.execute(select(func.count()).select_from(Application).where(Application.job_id == j.id))).scalar_one()
        u = (await db.execute(select(func.count()).select_from(Application).where(Application.job_id == j.id, *UNREVIEWED))).scalar_one()
        items.append(JobListItem(id=j.id, title=j.title, status=j.status, job_category=j.job_category, deadline_at=j.deadline_at, applicant_count=n,
                                 unreviewed_count=u, coding_test_enabled=j.coding_test_enabled, updated_at=j.updated_at))
    return JobListOut(items=items, page=page, limit=limit, total=total)


@router.post("/jobs", response_model=JobOut, status_code=201)
async def create_job(body: JobWrite, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> JobOut:
    if not body.title:
        raise ApiError(422, "VALIDATION_ERROR", "공고 제목은 필수입니다", {"fields": [{"field": "title", "message": "필수 항목입니다"}]})
    data = body.model_dump(exclude={"updated_at"}, exclude_unset=True)
    job = JobPosting(company_id=company_of(user), status=JobStatus.DRAFT, **data)
    db.add(job)
    await db.flush()
    db.add_all([EvalWeight(job_id=job.id), FollowupRule(job_id=job.id)])  # 기본값 (가중치 합 100, 꼬리질문 최대 2)
    _audit(db, user, job.id, "created")
    await db.commit()
    return await _full(db, job)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> JobOut:
    return await _full(db, await _job(db, job_id, user))


@router.put("/jobs/{job_id}", response_model=JobOut)
async def update_job(job_id: uuid.UUID, body: JobWrite, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> JobOut:
    job = await _job(db, job_id, user, editable=True)
    if body.updated_at is not None and abs((body.updated_at - job.updated_at).total_seconds()) > 0.001:
        raise ApiError(409, "STALE_UPDATE", "다른 곳에서 수정되었습니다. 새로고침 후 다시 시도해 주세요")
    data = body.model_dump(exclude={"updated_at"}, exclude_unset=True)
    if "title" in data and not data["title"]:
        raise ApiError(422, "VALIDATION_ERROR", "공고 제목은 비울 수 없습니다", {"fields": [{"field": "title", "message": "필수 항목입니다"}]})
    for k, v in data.items():
        setattr(job, k, v)
    job.updated_at = utcnow()
    await db.commit()
    return await _full(db, job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> Response:
    job = await _job(db, job_id, user)
    job.status = JobStatus.DELETED  # 소프트 삭제 (지원 기록 보존)
    _audit(db, user, job.id, "deleted")
    await db.commit()
    return Response(status_code=204)


@router.put("/jobs/{job_id}/questions", response_model=list[QuestionOut])
async def put_questions(job_id: uuid.UUID, body: QuestionsPut, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> list[QuestionOut]:
    """직접 등록 질문 세트(≤10)를 통째로 교체한다. 인적 속성 질문은 서버가 최종 거부(G4). 빈 슬롯은 면접 시 자동 생성된다."""
    job = await _job(db, job_id, user, editable=True)
    for i, it in enumerate(body.items):
        try:
            check_forbidden(it.text)
        except GuardrailError as e:
            raise ApiError(422, "FORBIDDEN_QUESTION", "채용 공정성 정책에 따라 사용할 수 없는 질문입니다", {"index": i}) from e
    await db.execute(delete(JobQuestion).where(JobQuestion.job_id == job.id, JobQuestion.order_no.is_not(None)))
    await db.flush()
    rows = [JobQuestion(job_id=job.id, source=QuestionSource.MANUAL, text=it.text, category=it.category, time_limit_sec=it.time_limit_sec, order_no=n)
            for n, it in enumerate(body.items, start=1)]
    db.add_all(rows)
    job.updated_at = utcnow()
    await db.commit()
    return [_q(r) for r in rows]


@router.put("/jobs/{job_id}/weights", response_model=WeightsOut)
async def put_weights(job_id: uuid.UUID, body: WeightsPut, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> WeightsOut:
    job = await _job(db, job_id, user, editable=True)
    w = body.weights
    total = sum(getattr(w, k) for k in WEIGHT_KEYS)
    if total != 100:
        raise ApiError(422, "WEIGHTS_SUM_INVALID", "가중치 합계는 100이어야 합니다", {"sum": total, "needed": 100 - total})
    if not job.coding_test_enabled and w.code_quality != 0:
        raise ApiError(422, "WEIGHTS_SUM_INVALID", "코딩테스트가 꺼져 있으면 코드 품질 가중치는 0이어야 합니다", {"field": "code_quality"})
    row, _ = await _ensure_settings(db, job)
    for k in WEIGHT_KEYS:
        setattr(row, k, getattr(w, k))
    row.gaze_penalty_enabled = body.gaze_penalty_enabled
    old = (job.cutoff_score, job.cutoff_margin)
    job.cutoff_score = body.cutoff_score
    job.cutoff_margin = body.cutoff_margin
    if old != (job.cutoff_score, job.cutoff_margin):  # 합격선이 바뀌면 리포트가 끝난 지원자의 예상 합불만 재계산 (점수는 불변, TRD §6.3)
        apps = (await db.execute(select(Application).where(Application.job_id == job.id, Application.status == ApplicationStatus.REPORT_READY,
                                                           Application.ai_total_score.is_not(None)))).scalars().all()
        for a in apps:
            a.ai_pass_prediction = scoring.predict(float(a.ai_total_score), body.cutoff_score, body.cutoff_margin)  # type: ignore[assignment]
    job.updated_at = utcnow()
    await db.commit()
    return WeightsOut(weights=w, gaze_penalty_enabled=body.gaze_penalty_enabled, cutoff_score=body.cutoff_score, cutoff_margin=body.cutoff_margin)


@router.put("/jobs/{job_id}/followup-rules", response_model=FollowupRulesPut)
async def put_followup_rules(job_id: uuid.UUID, body: FollowupRulesPut, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> FollowupRulesPut:
    job = await _job(db, job_id, user, editable=True)
    _, row = await _ensure_settings(db, job)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    job.updated_at = utcnow()
    await db.commit()
    return body


# ── 질문 뱅크 ────────────────────────────────────────────────────────────────
async def _set_bank_status(db: AsyncSession, job_id: uuid.UUID, status: QuestionBankStatus, generated: bool = False) -> None:
    """백그라운드 상태 변경은 사용자가 보는 `updated_at`(동시 편집 감지 기준)을 올리지 않는다 — 올리면 작성 중인 화면의 다음 저장이 STALE_UPDATE 로 막힌다."""
    vals: dict = {"question_bank_status": status, "updated_at": JobPosting.updated_at}
    if generated:
        vals["question_bank_generated_at"] = utcnow()
    await db.execute(sa_update(JobPosting).where(JobPosting.id == job_id).values(**vals))


async def _bank_task(svc: Services, sm: async_sessionmaker, job_id: uuid.UUID) -> None:
    from app.ai.chains.bank_chain import generate_bank

    async with sm() as db:
        job = await db.get(JobPosting, job_id)
        args = dict(title=job.title, duties=job.duties or "", requirements=job.requirements or "", preferred=job.preferred or "")
        await _set_bank_status(db, job_id, QuestionBankStatus.RUNNING)
        await db.commit()
    status = QuestionBankStatus.FAILED
    items = []
    try:
        items = await generate_bank(svc.report_llm_factory or svc.llm_factory, timeout_s=150, **args)
        status = QuestionBankStatus.DONE if items else QuestionBankStatus.FAILED
    except LLMUnavailable:
        pass
    except Exception:  # noqa: BLE001  원문 비로깅
        pass
    async with sm() as db:
        if items:  # 기존 후보만 교체한다 (세트에 추가된 직접 등록 질문은 유지)
            await db.execute(delete(JobQuestion).where(JobQuestion.job_id == job_id, JobQuestion.order_no.is_(None)))
            db.add_all([JobQuestion(job_id=job_id, source=QuestionSource.AI_BANK, text=i.question, category=i.category) for i in items])
        await _set_bank_status(db, job_id, status, generated=bool(items))
        await db.commit()


@router.post("/jobs/{job_id}/question-bank/generate", status_code=202)
async def generate_question_bank(job_id: uuid.UUID, request: Request, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    from app.worker.queue import interview_active

    job = await _job(db, job_id, user, editable=True)
    if not (job.duties or job.requirements):
        raise ApiError(422, "JD_REQUIRED", "주요 업무 또는 지원 요건을 먼저 저장해 주세요")
    if job.question_bank_status in (QuestionBankStatus.QUEUED, QuestionBankStatus.RUNNING):
        raise ApiError(409, "BANK_IN_PROGRESS", "이미 추출 중입니다")
    if await interview_active(request.app.state.sessionmaker):  # 면접 중에는 무거운 후처리를 하지 않는다 (TRD §2.5)
        raise ApiError(503, "BUSY_INTERVIEW_ACTIVE", "지금은 면접이 진행 중이라 잠시 후 시도해 주세요", headers={"Retry-After": "60"})
    await _set_bank_status(db, job_id, QuestionBankStatus.QUEUED)
    await db.commit()
    svc = request.app.state.services
    svc.spawn(_bank_task(svc, request.app.state.sessionmaker, job_id), f"bank:{job_id}")
    return {"status": "queued"}


@router.get("/jobs/{job_id}/question-bank", response_model=BankOut)
async def get_question_bank(job_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> BankOut:
    job = await _job(db, job_id, user)
    qs = (await db.execute(select(JobQuestion).where(JobQuestion.job_id == job.id, JobQuestion.order_no.is_(None),
                                                     JobQuestion.source == QuestionSource.AI_BANK).order_by(JobQuestion.created_at))).scalars().all()
    msg = "JD가 너무 짧거나 AI 연결에 실패했어요. 주요 업무·요건을 더 구체적으로 쓰거나 잠시 후 다시 시도하세요" if job.question_bank_status == QuestionBankStatus.FAILED else None
    return BankOut(status=job.question_bank_status.value, items=[_q(q) for q in qs], message=msg)  # type: ignore[arg-type]


# ── 게시 · 마감 ──────────────────────────────────────────────────────────────
@router.post("/jobs/{job_id}/publish", response_model=JobOut)
async def publish_job(job_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> JobOut:
    job = await _job(db, job_id, user, editable=True)
    if job.status == JobStatus.OPEN:
        return await _full(db, job)
    missing = [k for k, v in (("title", job.title), ("job_category", job.job_category), ("headcount", job.headcount), ("deadline_at", job.deadline_at),
                              ("duties", job.duties), ("requirements", job.requirements)) if not v]
    if job.deadline_at is not None and job.deadline_at <= utcnow():
        missing.append("deadline_at")
    if job.coding_test_enabled and not job.coding_test_time_limit_sec:
        missing.append("coding_test_time_limit_sec")
    if missing:
        raise ApiError(422, "PUBLISH_VALIDATION", "게시에 필요한 항목이 부족합니다", {"missing": sorted(set(missing))})
    qs = (await db.execute(select(JobQuestion).where(JobQuestion.job_id == job.id))).scalars().all()
    manual, bank = sum(1 for q in qs if q.order_no is not None), sum(1 for q in qs if q.order_no is None)
    if manual + bank < POOL_MIN:
        raise ApiError(422, "QUESTION_POOL_INSUFFICIENT", "질문이 부족합니다", {"manual": manual, "bank": bank, "needed": POOL_MIN - manual - bank})
    job.status = JobStatus.OPEN  # cutoff_score 미설정은 거부하지 않는다(경고만)
    job.updated_at = utcnow()
    _audit(db, user, job.id, "published")
    await db.commit()
    return await _full(db, job)


@router.post("/jobs/{job_id}/close", response_model=JobOut)
async def close_job(job_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> JobOut:
    job = await _job(db, job_id, user)
    if job.status != JobStatus.OPEN:
        raise ApiError(409, "JOB_NOT_OPEN", "게시 중인 공고만 마감할 수 있습니다", {"status": job.status.value})
    job.status = JobStatus.CLOSED  # 재오픈 불가
    _audit(db, user, job.id, "closed")
    await db.commit()
    return await _full(db, job)


_ = datetime
