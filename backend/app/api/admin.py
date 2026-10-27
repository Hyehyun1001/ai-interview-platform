"""관리자(담당자) REST (TRD §7.6, §7.8). 모든 조회는 호출자의 company_id 로 스코프한다 (NFR-S6) — 다른 회사의 자원은 404."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import psutil
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_db, get_settings_dep, require_role
from app.core.errors import ApiError
from app.models import (Application, AuditLog, BackgroundJob, EvaluationReport, GazeEvent, InterviewSession, InterviewTurn, JobPosting, LlmAuditLog,
                        Notification, ReportScore, Schedule, User, VoiceTimeline)
from app.models.base import utcnow
from app.models.enums import ApplicationStatus, FinalDecision, JobStatus, QueueStatus, ReportStatus, ScheduleType, SessionState, UserRole
from app.schemas.admin import (ApplicantPage, ApplicationDetail, DashboardResponse, DashboardStats, DashboardSummary, ExternalTransfer,
                               GazeEventOut, JobCategoryStat, ModelState, MonthlyCount, NotificationItem, NotificationsResponse,
                               OpenJobs, Range, RecentApplicant, RecentJob, ScheduleCreate, ScheduleCreated, ScheduleOut,
                               SystemMetrics, SystemModels, TimelineResponse, TimelineSegment, TimelineTurn, TimelineWord,
                               TurnReview, TurnReviewScore, UpcomingInterviews)
from app.models.enums import TimelineKind

router = APIRouter(prefix="/admin", tags=["admin"])
RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}
Staff = require_role(UserRole.RECRUITER, UserRole.ADMIN)


def company_of(user: User) -> uuid.UUID:
    if user.company_id is None:  # 회사에 소속되지 않은 담당자는 어떤 데이터도 볼 수 없다
        raise ApiError(403, "FORBIDDEN", "소속 회사가 없는 계정입니다")
    return user.company_id


def _f(v) -> float | None:  # noqa: ANN001  Decimal → float
    return None if v is None else float(v)


def _applicant_query(company_id: uuid.UUID) -> Select:
    return (select(Application, User.name, JobPosting, InterviewSession, EvaluationReport.status)
            .join(JobPosting, JobPosting.id == Application.job_id).join(User, User.id == Application.user_id)
            .join(InterviewSession, InterviewSession.application_id == Application.id)
            .outerjoin(EvaluationReport, EvaluationReport.session_id == InterviewSession.id)
            .where(JobPosting.company_id == company_id, InterviewSession.state == SessionState.FINISHED, InterviewSession.ended_at.is_not(None)))


def _to_recent(row) -> RecentApplicant:  # noqa: ANN001
    app, name, job, sess, rstatus = row
    return RecentApplicant(application_id=app.id, name=name, job_id=job.id, job_title=job.title, ai_total_score=_f(app.ai_total_score),
                           ai_pass_prediction=app.ai_pass_prediction, report_status=rstatus or ReportStatus.QUEUED,
                           final_decision=app.final_decision, interview_ended_at=sess.ended_at, reviewed=app.first_reviewed_at is not None)


UNREVIEWED = (Application.status == ApplicationStatus.REPORT_READY, Application.final_decision == FinalDecision.PENDING,
              Application.first_reviewed_at.is_(None))


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(range_: Range = Query("30d", alias="range"), user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> DashboardResponse:
    cid = company_of(user)
    now = utcnow()
    local_now = now.astimezone()  # 서버 로컬 시간대 기준 "오늘"
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    sched = select(Schedule.starts_at).where(Schedule.company_id == cid, Schedule.type.in_([ScheduleType.INTERVIEW1, ScheduleType.INTERVIEW2]),
                                              Schedule.starts_at >= now)
    starts = list((await db.execute(sched)).scalars())
    upcoming = UpcomingInterviews(total=len(starts), today=sum(1 for t in starts if t < day_end), within_7d=sum(1 for t in starts if t < now + timedelta(days=7)))

    open_jobs = (await db.execute(select(JobPosting).where(JobPosting.company_id == cid, JobPosting.status == JobStatus.OPEN))).scalars().all()
    unreviewed = (await db.execute(select(func.count()).select_from(Application).join(JobPosting, JobPosting.id == Application.job_id)
                                   .where(JobPosting.company_id == cid, *UNREVIEWED))).scalar_one()
    closing = sum(1 for j in open_jobs if j.deadline_at is not None and now < j.deadline_at <= now + timedelta(hours=24))

    since = now - timedelta(days=RANGE_DAYS[range_])
    stat_rows = (await db.execute(
        select(JobPosting.job_category, Application.ai_total_score, Application.final_decision)
        .join(JobPosting, JobPosting.id == Application.job_id).join(InterviewSession, InterviewSession.application_id == Application.id)
        .where(JobPosting.company_id == cid, Application.ai_total_score.is_not(None), InterviewSession.ended_at >= since))).all()
    groups: dict[str, list[tuple[float, FinalDecision]]] = {}
    for cat, score, dec in stat_rows:
        groups.setdefault(cat or "기타", []).append((float(score), dec))
    by_cat = []
    for cat, items in sorted(groups.items()):
        decided = [d for _, d in items if d != FinalDecision.PENDING]
        by_cat.append(JobCategoryStat(category=cat, avg_score=round(sum(s for s, _ in items) / len(items), 1),
                                      pass_rate=(sum(1 for d in decided if d == FinalDecision.PASS) / len(decided)) if decided else None,
                                      applicants=len(items)))

    month_start = (local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=31 * 5)).replace(day=1)
    created = (await db.execute(select(Application.created_at).join(JobPosting, JobPosting.id == Application.job_id)
                                .where(JobPosting.company_id == cid, Application.created_at >= month_start.astimezone(timezone.utc)))).scalars()
    counts: dict[str, int] = {}
    for c in created:
        key = c.astimezone().strftime("%Y-%m")
        counts[key] = counts.get(key, 0) + 1
    months, cur = [], local_now.replace(day=1)
    for _ in range(6):
        months.append(cur.strftime("%Y-%m"))
        cur = (cur - timedelta(days=1)).replace(day=1)
    monthly = [MonthlyCount(month=m, count=counts.get(m, 0)) for m in reversed(months)]

    jobs = (await db.execute(select(JobPosting).where(JobPosting.company_id == cid, JobPosting.status != JobStatus.DELETED)
                             .order_by(JobPosting.updated_at.desc()).limit(6))).scalars().all()
    recent_jobs = []
    for j in jobs:
        n = (await db.execute(select(func.count()).select_from(Application).where(Application.job_id == j.id))).scalar_one()
        u = (await db.execute(select(func.count()).select_from(Application).where(Application.job_id == j.id, *UNREVIEWED))).scalar_one()
        recent_jobs.append(RecentJob(id=j.id, title=j.title, status=j.status, deadline_at=j.deadline_at, applicant_count=n, unreviewed_count=u,
                                     coding_test_enabled=j.coding_test_enabled, coding_test_time_limit_sec=j.coding_test_time_limit_sec,
                                     updated_at=j.updated_at))

    rows = (await db.execute(_applicant_query(cid).order_by(InterviewSession.ended_at.desc()).limit(8))).all()
    return DashboardResponse(
        range=range_, summary=DashboardSummary(upcoming_interviews=upcoming, open_jobs=OpenJobs(total=len(open_jobs), coding_on=sum(1 for j in open_jobs if j.coding_test_enabled)),
                                              unreviewed_applicants=unreviewed, closing_soon_jobs=closing),
        stats=DashboardStats(by_job_category=by_cat, monthly_applicants=monthly), recent_jobs=recent_jobs,
        recent_completed_applicants=[_to_recent(r) for r in rows])


@router.get("/applications", response_model=ApplicantPage)
async def list_applications(stage: str = Query("interview_done", pattern="^(interview_done|report_ready|all)$"),
                            review: str | None = Query(None, pattern="^unreviewed$"), job_id: uuid.UUID | None = None,
                            sort: str = Query("ended_at_desc", pattern="^(ended_at_desc|score_desc)$"), page: int = Query(1, ge=1),
                            limit: int = Query(20, ge=1, le=100), user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> ApplicantPage:
    cid = company_of(user)
    q = _applicant_query(cid)
    if stage == "report_ready":
        q = q.where(Application.status == ApplicationStatus.REPORT_READY)
    if review == "unreviewed":
        q = q.where(*UNREVIEWED)
    if job_id:
        q = q.where(Application.job_id == job_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    order = Application.ai_total_score.desc().nulls_last() if sort == "score_desc" else InterviewSession.ended_at.desc()
    rows = (await db.execute(q.order_by(order).offset((page - 1) * limit).limit(limit))).all()
    return ApplicantPage(items=[_to_recent(r) for r in rows], page=page, limit=limit, total=total)


async def _scoped_application(db: AsyncSession, application_id: uuid.UUID, user: User):  # noqa: ANN202
    cid = company_of(user)
    row = (await db.execute(_applicant_query(cid).where(Application.id == application_id))).first()
    if row is None:  # 다른 회사 · 미완료 · 없음 모두 같은 404 (존재 여부 비노출)
        raise ApiError(404, "NOT_FOUND", "지원자를 찾을 수 없습니다")
    return row


def _audit(db: AsyncSession, request: Request, user: User, action: str, target_id: uuid.UUID, detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=user.id, action=action, target_type="application", target_id=target_id,
                    ip=request.client.host if request.client else None, detail=detail))


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
async def application_detail(application_id: uuid.UUID, request: Request, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> ApplicationDetail:
    """읽기 전용 — 열람 확인(first_reviewed_at)은 별도 POST .../reviewed (prefetch 로 상태가 바뀌지 않게)."""
    row = await _scoped_application(db, application_id, user)
    r = _to_recent(row)
    _audit(db, request, user, "view_application", application_id)
    await db.commit()
    return ApplicationDetail(application_id=r.application_id, applicant_name=r.name, job_id=r.job_id, job_title=r.job_title, ai_total_score=r.ai_total_score,
                             ai_pass_prediction=r.ai_pass_prediction, report_status=r.report_status, final_decision=r.final_decision,
                             interview_ended_at=r.interview_ended_at)


@router.post("/applications/{application_id}/reviewed", status_code=204)
async def mark_reviewed(application_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> Response:
    """최초 1회만 기록, 이후 호출은 멱등 204 (회사 단위 최초 열람 기준)."""
    app = (await _scoped_application(db, application_id, user))[0]
    if app.first_reviewed_at is None:
        app.first_reviewed_at, app.first_reviewed_by = utcnow(), user.id
        await db.commit()
    return Response(status_code=204)


@router.get("/applications/{application_id}/timeline", response_model=TimelineResponse)
async def timeline(application_id: uuid.UUID, request: Request, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> TimelineResponse:
    row = await _scoped_application(db, application_id, user)
    sess: InterviewSession = row[3]
    media = request.app.state.session_manager.engines.media
    turns = (await db.execute(select(InterviewTurn).where(InterviewTurn.session_id == sess.id).order_by(InterviewTurn.turn_no))).scalars().all()
    segs = (await db.execute(select(VoiceTimeline).join(InterviewTurn, InterviewTurn.id == VoiceTimeline.turn_id)
                             .where(InterviewTurn.session_id == sess.id).order_by(VoiceTimeline.start_ms))).scalars().all()
    gazes = (await db.execute(select(GazeEvent).where(GazeEvent.session_id == sess.id).order_by(GazeEvent.start_ms))).scalars().all()
    report = (await db.execute(select(EvaluationReport).where(EvaluationReport.session_id == sess.id))).scalar_one_or_none()
    scores = (await db.execute(select(ReportScore).where(ReportScore.report_id == report.id, ReportScore.turn_id.is_not(None)))).scalars().all() if report else []
    out = []
    for t in turns:
        pcm = media.answer_path(sess.id, t.id)
        has_audio = pcm.exists() and pcm.stat().st_size > 0
        duration = t.answer_duration_ms or (pcm.stat().st_size // 32 if has_audio else 0)  # 16kHz mono s16le = 32 bytes/ms
        rows = [s for s in segs if s.turn_id == t.id]
        if rows:
            segments = [TimelineSegment(start_ms=s.start_ms, end_ms=s.end_ms, kind=s.kind, text=s.text, ai_comment=s.ai_comment, severity=s.severity,
                                        words=[TimelineWord(**w) for w in s.words] if s.words else None) for s in rows]
        else:
            segments = []
        if t.answer_text and duration > 0 and not any(s.kind == TimelineKind.SPEECH for s in segments):
            # 전사는 암호화 컬럼에서 그대로 읽는다(voice_timeline 에 평문 사본을 두지 않는다). 하이라이트가 있어도 발화 구간을 항상 맨 앞에 둔다
            segments.insert(0, TimelineSegment(start_ms=0, end_ms=duration, kind=TimelineKind.SPEECH, text=t.answer_text))
        ts = [TurnReviewScore(criterion=sc.criterion.value, score=float(sc.score), comment=sc.comment) for sc in scores if sc.turn_id == t.id]
        out.append(TimelineTurn(turn_id=t.id, turn_no=t.turn_no, kind=t.kind, question=t.question_text,
                                audio_url=f"/api/v1/media/turns/{t.id}/audio" if has_audio else None, duration_ms=duration, segments=segments,
                                gaze_events=[GazeEventOut(start_ms=g.start_ms, end_ms=g.end_ms, kind=g.kind.value) for g in gazes if g.turn_id == t.id],
                                answer_text=t.answer_text, review=TurnReview(scores=ts) if ts else None))
    _audit(db, request, user, "view_timeline", application_id)
    await db.commit()
    return TimelineResponse(application_id=application_id, turns=out)


# ── 일정 ──
@router.post("/schedules", response_model=ScheduleCreated, status_code=201)
async def create_schedule(body: ScheduleCreate, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> ScheduleCreated:
    cid = company_of(user)
    if body.job_id is not None and (await db.execute(select(JobPosting.id).where(JobPosting.id == body.job_id, JobPosting.company_id == cid))).first() is None:
        raise ApiError(404, "NOT_FOUND", "공고를 찾을 수 없습니다")
    if body.application_id is not None:
        await _scoped_application_any(db, body.application_id, cid)
    row = Schedule(company_id=cid, job_id=body.job_id, application_id=body.application_id, title=body.title, starts_at=body.starts_at,
                   ends_at=body.ends_at, type=body.type)
    db.add(row)
    await db.commit()
    return ScheduleCreated(id=row.id)


async def _scoped_application_any(db: AsyncSession, application_id: uuid.UUID, cid: uuid.UUID) -> None:
    ok = (await db.execute(select(Application.id).join(JobPosting, JobPosting.id == Application.job_id)
                           .where(Application.id == application_id, JobPosting.company_id == cid))).first()
    if ok is None:
        raise ApiError(404, "NOT_FOUND", "지원자를 찾을 수 없습니다")


@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, user: User = Depends(Staff),
                         db: AsyncSession = Depends(get_db)) -> list[ScheduleOut]:
    q = select(Schedule).where(Schedule.company_id == company_of(user)).order_by(Schedule.starts_at)
    if from_ is not None:
        q = q.where(Schedule.starts_at >= from_)
    if to is not None:
        q = q.where(Schedule.starts_at < to)
    return [ScheduleOut(id=s.id, title=s.title, type=s.type, job_id=s.job_id, application_id=s.application_id, starts_at=s.starts_at, ends_at=s.ends_at)
            for s in (await db.execute(q.limit(500))).scalars()]


# ── 알림 ──
@router.get("/notifications", response_model=NotificationsResponse)
async def notifications(user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> NotificationsResponse:
    rows = (await db.execute(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50))).scalars().all()
    unread = (await db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)))).scalar_one()
    return NotificationsResponse(items=[NotificationItem(id=n.id, type=n.type, payload=n.payload, read_at=n.read_at, created_at=n.created_at) for n in rows],
                                 unread_count=unread)


@router.post("/notifications/{notification_id}/read", status_code=204)
async def read_notification(notification_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> Response:
    n = (await db.execute(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))).scalar_one_or_none()
    if n is None:
        raise ApiError(404, "NOT_FOUND", "알림을 찾을 수 없습니다")
    if n.read_at is None:
        n.read_at = utcnow()
        await db.commit()
    return Response(status_code=204)


# ── 시스템 ──
def pressure_for(free_gb: float) -> str:
    """TRD §2.5: normal ≥ 2.5GB, warn 1.2~2.5GB, critical < 1.2GB (Ollama 지연 조건은 런타임 경량 모드가 별도로 다룬다)."""
    return "normal" if free_gb >= 2.5 else "warn" if free_gb >= 1.2 else "critical"


async def _ollama_loaded(settings: Settings) -> bool | None:
    try:
        async with httpx.AsyncClient(timeout=1.0) as c:  # 로컬 Ollama 만 조회 (외부 전송 아님)
            r = await c.get(f"{settings.ollama_base_url}/api/ps")
        return any(m.get("name") == settings.ollama_model or m.get("model") == settings.ollama_model for m in r.json().get("models", []))
    except Exception:  # noqa: BLE001
        return None


@router.get("/system/metrics", response_model=SystemMetrics)
async def system_metrics(request: Request, user: User = Depends(Staff), settings: Settings = Depends(get_settings_dep),
                         db: AsyncSession = Depends(get_db)) -> SystemMetrics:
    free_gb = round(psutil.virtual_memory().available / 1024**3, 1)
    engines = request.app.state.session_manager.engines
    store = request.app.state.services._store  # noqa: SLF001  이미 생성된 경우에만 (조회 때문에 모델을 올리지 않는다)
    external = (await db.execute(select(func.count()).select_from(LlmAuditLog))).scalar_one()
    tts_edge = settings.tts_provider == "edge"
    return SystemMetrics(
        pressure=pressure_for(free_gb), free_gb=free_gb,  # type: ignore[arg-type]
        models=SystemModels(
            llm=ModelState(name=settings.ollama_model, loaded=await _ollama_loaded(settings)),
            stt=ModelState(name=getattr(engines.stt, "model_name", settings.stt_model), loaded=(getattr(engines.stt, "_model", None) is not None) if hasattr(engines.stt, "_model") else None),
            tts=ModelState(name=settings.tts_provider, loaded=None),
            embed=ModelState(name=settings.embed_model, loaded=getattr(getattr(store, "embedder", None), "loaded", None))),
        external_transfer=ExternalTransfer(enabled=tts_edge, tts_edge=tts_edge, cloud_fallback=False, count=external))


@router.post("/applications/{application_id}/report/regenerate", status_code=202)
async def regenerate_report(application_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """리포트가 failed 일 때만 재생성 잡을 다시 넣는다. queued/running/done 이면 409 (중복 생성 방지)."""
    row = await _scoped_application(db, application_id, user)
    sess: InterviewSession = row[3]
    report = (await db.execute(select(EvaluationReport).where(EvaluationReport.session_id == sess.id))).scalar_one_or_none()
    if report is None or report.status != ReportStatus.FAILED:
        raise ApiError(409, "REPORT_NOT_FAILED", "실패한 리포트만 다시 생성할 수 있습니다", {"status": report.status.value if report else "none"})
    report.status = ReportStatus.QUEUED
    db.add(BackgroundJob(type="report", payload={"session_id": str(sess.id)}, status=QueueStatus.QUEUED))
    await db.commit()
    return {"report_status": "queued"}
