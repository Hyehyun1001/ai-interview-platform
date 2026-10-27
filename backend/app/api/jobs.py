"""공고 조회·지원 (TRD §7.2) + 내 지원 목록 (§7.1)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.core.errors import ApiError
from app.models import Application, Company, EvaluationReport, InterviewSession, JobPosting, Notification, User
from app.models.base import utcnow
from app.models.enums import FinalDecision, JobStatus, UserRole
from app.schemas.jobs import ApplyRequest, ApplyResponse, JobDetail, JobList, JobSummary, MyApplication, MyJobRef

router = APIRouter(tags=["jobs"])
CONSENT_VERSION_MAX = 20


def _open_filter():  # noqa: ANN202
    now = datetime.now(timezone.utc)
    return (JobPosting.status == JobStatus.OPEN, or_(JobPosting.deadline_at.is_(None), JobPosting.deadline_at > now))


def _summary(job: JobPosting, company: str, applied: bool) -> JobSummary:
    return JobSummary(id=job.id, title=job.title, company_name=company, job_category=job.job_category, deadline_at=job.deadline_at,
                      headcount=job.headcount, coding_test_enabled=job.coding_test_enabled, applicant_applied=applied)


@router.get("/jobs", response_model=JobList)
async def list_jobs(category: str | None = None, q: str | None = Query(default=None, max_length=100), page: int = Query(1, ge=1),
                    limit: int = Query(20, ge=1, le=100), user: User = Depends(require_role(UserRole.APPLICANT)),
                    db: AsyncSession = Depends(get_db)) -> JobList:
    cond = list(_open_filter())
    if category:
        cond.append(JobPosting.job_category == category)
    if q:
        like = f"%{q.strip()}%"
        cond.append(or_(JobPosting.title.like(like), JobPosting.duties.like(like), JobPosting.requirements.like(like)))
    total = (await db.execute(select(func.count()).select_from(JobPosting).where(*cond))).scalar_one()
    rows = (await db.execute(
        select(JobPosting, Company.name).join(Company, Company.id == JobPosting.company_id).where(*cond)
        .order_by(JobPosting.deadline_at.is_(None), JobPosting.deadline_at, JobPosting.created_at.desc())
        .offset((page - 1) * limit).limit(limit))).all()
    applied = set((await db.execute(select(Application.job_id).where(Application.user_id == user.id))).scalars())
    return JobList(items=[_summary(j, c, j.id in applied) for j, c in rows], page=page, limit=limit, total=total)


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def get_job(job_id: uuid.UUID, user: User = Depends(require_role(UserRole.APPLICANT)), db: AsyncSession = Depends(get_db)) -> JobDetail:
    row = (await db.execute(select(JobPosting, Company.name).join(Company, Company.id == JobPosting.company_id)
                            .where(JobPosting.id == job_id, JobPosting.status.in_([JobStatus.OPEN, JobStatus.CLOSED])))).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "공고를 찾을 수 없습니다")
    job, company = row
    await db.execute(update(JobPosting).where(JobPosting.id == job.id).values(view_count=JobPosting.view_count + 1, updated_at=JobPosting.updated_at))  # 조회수는 담당자의 편집 기준(updated_at)을 바꾸지 않는다
    app_id = (await db.execute(select(Application.id).where(Application.user_id == user.id, Application.job_id == job.id))).scalar_one_or_none()
    await db.commit()
    base = _summary(job, company, app_id is not None)
    return JobDetail(**base.model_dump(), duties=job.duties, requirements=job.requirements, preferred=job.preferred,
                     answer_time_limit_sec=job.answer_time_limit_sec, application_id=app_id)


@router.post("/jobs/{job_id}/apply", response_model=ApplyResponse, status_code=201)
async def apply(job_id: uuid.UUID, body: ApplyRequest, user: User = Depends(require_role(UserRole.APPLICANT)),
                db: AsyncSession = Depends(get_db)) -> ApplyResponse:
    if not body.consent:
        raise ApiError(422, "CONSENT_REQUIRED", "개인정보 수집·이용에 동의해야 지원할 수 있습니다", {"field": "consent"})
    job = (await db.execute(select(JobPosting).where(JobPosting.id == job_id))).scalar_one_or_none()
    if job is None or job.status in (JobStatus.DRAFT, JobStatus.DELETED):
        raise ApiError(404, "NOT_FOUND", "공고를 찾을 수 없습니다")
    if job.status != JobStatus.OPEN or (job.deadline_at is not None and job.deadline_at <= utcnow()):
        raise ApiError(409, "JOB_CLOSED", "마감된 공고입니다")
    existing = (await db.execute(select(Application.id).where(Application.user_id == user.id, Application.job_id == job_id))).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "ALREADY_APPLIED", "이미 지원한 공고입니다", {"application_id": str(existing)})
    app = Application(user_id=user.id, job_id=job_id, consent_at=utcnow(), consent_version=body.consent_version)
    db.add(app)
    try:
        await db.commit()
    except IntegrityError as e:  # 동시 지원 경합: UNIQUE(user_id, job_id)
        await db.rollback()
        existing = (await db.execute(select(Application.id).where(Application.user_id == user.id, Application.job_id == job_id))).scalar_one()
        raise ApiError(409, "ALREADY_APPLIED", "이미 지원한 공고입니다", {"application_id": str(existing)}) from e
    staff = (await db.execute(select(User.id).where(User.company_id == job.company_id, User.role.in_([UserRole.RECRUITER, UserRole.ADMIN])))).scalars().all()
    for uid in staff:  # 담당자 알림: 식별자만 담는다(지원자 이름·연락처는 알림 payload 에 넣지 않는다)
        db.add(Notification(user_id=uid, type="new_application", payload={"application_id": str(app.id), "job_id": str(job.id)}))
    await db.commit()
    return ApplyResponse(application_id=app.id)


@router.get("/me/applications", response_model=list[MyApplication])
async def my_applications(user: User = Depends(require_role(UserRole.APPLICANT)), db: AsyncSession = Depends(get_db)) -> list[MyApplication]:
    rows = (await db.execute(
        select(Application, JobPosting, InterviewSession.id, EvaluationReport.status)
        .join(JobPosting, JobPosting.id == Application.job_id)
        .outerjoin(InterviewSession, InterviewSession.application_id == Application.id)
        .outerjoin(EvaluationReport, EvaluationReport.session_id == InterviewSession.id)
        .where(Application.user_id == user.id).order_by(Application.created_at.desc()))).all()
    out = []
    for app, job, sid, rstatus in rows:
        # 합불은 담당자가 확정하고 안내 메일이 나간 뒤에만 지원자에게 보인다 (PRD)
        result = app.final_decision if app.result_notified_at and app.final_decision != FinalDecision.PENDING else None
        out.append(MyApplication(application_id=app.id, job=MyJobRef(id=job.id, title=job.title, deadline_at=job.deadline_at),
                                 status=app.status, session_id=sid, report_status=rstatus, result=result, applied_at=app.created_at))
    return out


_ = Response  # re-export guard for linters
