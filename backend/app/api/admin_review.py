"""지원자 비교 · 최종 합불 결정 · 안내 메일 (TRD §7.6). 모든 조회·변경은 company_id 스코프이고 행위는 audit_logs 에 남긴다."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import Staff, _audit, _scoped_application
from app.core.deps import get_db
from app.core.errors import ApiError
from app.models import Application, AuditLog, EvaluationReport, RecruiterNote, ReportScore, User
from app.models.base import utcnow
from app.models.enums import ApplicationStatus, FinalDecision, ReportStatus
from app.schemas.admin_review import CompareApplicant, CompareResponse, DecisionIn, DecisionOut, MailIn, MailOut, NoteIn, NoteOut
from app.services.mailer import MailNotConfigured, MailSendFailed

router = APIRouter(prefix="/admin", tags=["admin-review"])
CORE_AXES = ["concept_understanding", "logic", "delivery", "attitude", "job_expertise"]


@router.get("/applicants/compare", response_model=CompareResponse)
async def compare(ids: str = Query(..., max_length=200), user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> CompareResponse:
    try:
        parsed = [uuid.UUID(x) for x in ids.split(",") if x.strip()]
    except ValueError as e:
        raise ApiError(400, "COMPARE_INVALID_SELECTION", "지원자 ID 형식이 올바르지 않습니다") from e
    if len(parsed) != len(set(parsed)) or not 2 <= len(parsed) <= 3:
        raise ApiError(400, "COMPARE_INVALID_SELECTION", "2~3명의 서로 다른 지원자를 선택해 주세요")
    rows = []
    for aid in parsed:
        rows.append(await _scoped_application(db, aid, user))  # 접근 불가/없음 → 404
    if len({r[2].id for r in rows}) != 1:
        raise ApiError(400, "COMPARE_INVALID_SELECTION", "같은 공고의 지원자만 비교할 수 있어요")
    not_ready = [str(r[0].id) for r in rows if r[4] != ReportStatus.DONE]
    if not_ready:
        raise ApiError(409, "REPORT_NOT_READY", "리포트가 완료되지 않은 지원자가 있습니다", {"application_ids": not_ready})
    job = rows[0][2]
    out = []
    for app, name, _job, sess, _rs in rows:
        rep = (await db.execute(select(EvaluationReport).where(EvaluationReport.session_id == sess.id))).scalar_one()
        crit = {s.criterion.value: float(s.score) for s in (await db.execute(
            select(ReportScore).where(ReportScore.report_id == rep.id, ReportScore.turn_id.is_(None)))).scalars()}
        out.append(CompareApplicant(application_id=app.id, name=name, ai_total_score=float(app.ai_total_score) if app.ai_total_score is not None else None,
                                    ai_pass_prediction=app.ai_pass_prediction, criteria=crit, gaze_away_ratio=rep.gaze_away_ratio,
                                    strengths=[i["title"] for i in (rep.strengths or [])][:3], improvements=[i["title"] for i in (rep.improvements or [])][:3]))
    axes = [a for a in CORE_AXES if all(a in o.criteria for o in out)]
    if all("code_quality" in o.criteria for o in out):  # 세 명 모두 있을 때만 6축 (UI_SPEC ADM-05)
        axes.append("code_quality")
    return CompareResponse(job_id=job.id, job_title=job.title, axes=axes, applicants=out)


@router.post("/applications/{application_id}/decision", response_model=DecisionOut)
async def decide(application_id: uuid.UUID, body: DecisionIn, request: Request, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> DecisionOut:
    """재호출 허용(덮어쓰기). `pending` 은 결정 취소. 변경 전후 값은 audit_logs 에, 메모는 내부 메모(recruiter_notes)로 남긴다(감사 로그에 자유 텍스트 금지)."""
    app: Application = (await _scoped_application(db, application_id, user))[0]
    if app.status != ApplicationStatus.REPORT_READY:
        raise ApiError(409, "REPORT_NOT_READY", "리포트가 완료된 뒤에 결정할 수 있습니다", {"status": app.status.value})
    before = app.final_decision
    if app.result_notified_at is not None and body.decision != before and not body.acknowledge_notified:
        raise ApiError(409, "DECISION_ALREADY_NOTIFIED", "이미 결과 메일을 보냈습니다. 변경하시겠어요?")
    if body.decision != before:
        app.final_decision = body.decision
        app.decided_by, app.decided_at = (None, None) if body.decision == FinalDecision.PENDING else (user.id, utcnow())
    if body.memo:
        db.add(RecruiterNote(application_id=app.id, author_id=user.id, body=body.memo))
    _audit(db, request, user, "decide" if before == FinalDecision.PENDING else "change_decision", app.id,
           {"before": before.value, "after": body.decision.value, "has_memo": bool(body.memo), "acknowledged_notified": body.acknowledge_notified})
    await db.commit()
    return DecisionOut(final_decision=app.final_decision, decided_at=app.decided_at)


@router.get("/applications/{application_id}/notes", response_model=list[NoteOut])
async def list_notes(application_id: uuid.UUID, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> list[NoteOut]:
    """내부 메모 타임라인(최신순). 지원자에게는 노출되지 않는다 — 담당자 전용 + company_id 스코프."""
    await _scoped_application(db, application_id, user)
    rows = (await db.execute(select(RecruiterNote, User.name).outerjoin(User, User.id == RecruiterNote.author_id)
                             .where(RecruiterNote.application_id == application_id)
                             .order_by(RecruiterNote.created_at.desc()))).all()
    return [NoteOut(id=n.id, author_name=name, body=n.body, created_at=n.created_at, mine=n.author_id == user.id) for n, name in rows]


@router.post("/applications/{application_id}/notes", response_model=NoteOut, status_code=201)
async def add_note(application_id: uuid.UUID, body: NoteIn, request: Request, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> NoteOut:
    await _scoped_application(db, application_id, user)
    note = RecruiterNote(application_id=application_id, author_id=user.id, body=body.body)
    db.add(note)
    _audit(db, request, user, "add_note", application_id)  # 감사 로그에는 본문을 남기지 않는다
    await db.commit()
    return NoteOut(id=note.id, author_name=user.name, body=note.body, created_at=note.created_at, mine=True)


SUBJECTS = {"pass": "[{job}] 면접 결과 안내 - 합격", "fail": "[{job}] 면접 결과 안내", "schedule": "[{job}] 다음 전형 일정 안내"}
BODIES = {
    "pass": "{name}님, 안녕하세요.\n{job} 전형에 합격하셨음을 알려 드립니다. 이후 절차는 담당자가 별도로 안내드리겠습니다.\n지원해 주셔서 감사합니다.\n\n- AuraEval AI",
    "fail": "{name}님, 안녕하세요.\n{job} 전형에 지원해 주셔서 감사합니다. 신중히 검토한 결과 이번에는 함께하지 못하게 되었음을 알려 드립니다.\n앞날을 응원합니다.\n\n- AuraEval AI",
    "schedule": "{name}님, 안녕하세요.\n{job} 다음 전형 일정을 조율하고자 합니다. 아래 링크에서 가능한 일정을 선택해 주세요.\n{link}\n\n- AuraEval AI",
}


@router.post("/applications/{application_id}/mail", response_model=MailOut)
async def send_mail(application_id: uuid.UUID, body: MailIn, request: Request, user: User = Depends(Staff), db: AsyncSession = Depends(get_db)) -> MailOut:
    """결과 안내 메일. 본문에는 AI 점수·예상 합불을 넣지 않는다(공정성). pass/fail 템플릿은 final_decision 과 일치할 때만."""
    app, name, job, _sess, _rs = await _scoped_application(db, application_id, user)
    if body.template in ("pass", "fail") and app.final_decision.value != body.template:
        raise ApiError(409, "DECISION_MISMATCH", "최종 결정과 맞지 않는 안내 메일입니다", {"decision": app.final_decision.value})
    if body.template == "schedule" and not body.schedule_link:
        raise ApiError(422, "VALIDATION_ERROR", "일정 조율 링크가 필요합니다", {"fields": [{"field": "schedule_link", "message": "필수 항목입니다"}]})
    email = (await db.execute(select(User.email).where(User.id == app.user_id))).scalar_one()
    mailer = request.app.state.services.mailer
    text = BODIES[body.template].format(name=name, job=job.title, link=body.schedule_link or "")
    try:
        await mailer.send(email, SUBJECTS[body.template].format(job=job.title), text)
    except MailNotConfigured as e:
        raise ApiError(503, "MAIL_NOT_CONFIGURED", "사내 메일 서버(SMTP)가 설정되어 있지 않습니다") from e
    except MailSendFailed as e:
        raise ApiError(502, "MAIL_SEND_FAILED", "메일 발송에 실패했습니다. 잠시 후 다시 시도해 주세요") from e
    if body.template in ("pass", "fail"):
        app.result_notified_at = utcnow()
    _audit(db, request, user, "send_mail", app.id, {"template": body.template})
    await db.commit()
    return MailOut(sent=True, template=body.template, result_notified_at=app.result_notified_at)


_ = AuditLog
