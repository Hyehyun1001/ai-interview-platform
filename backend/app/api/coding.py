"""코딩테스트 REST (TRD §5, §7.8): 문제 · 샘플 실행 · 제출/채점 · 결과. 지원자 코드는 샌드박스 밖에서 실행하지 않는다."""
from __future__ import annotations

import logging
import uuid
from datetime import timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import Staff, company_of
from app.api.sessions import owned_session
from app.coding.judge import MAX_SOURCE_CHARS, CaseResult, SandboxUnavailable, judge
from app.coding.problems import LANGUAGES, STARTERS, Problem, pick_problem
from app.core.deps import get_current_user, get_db, get_settings_dep, require_role
from app.core.errors import ApiError
from app.models import Application, AuditLog, CodeSubmission, InterviewSession, InterviewTurn, JobPosting, User
from app.models.base import utcnow
from app.models.enums import SessionState, TurnKind, UserRole, Verdict
from app.schemas.coding import CaseOut, CodeIn, ExampleOut, LanguageOut, ProblemOut, ResultOut, RunOut, SubmitAccepted

router = APIRouter(tags=["coding"])
log = logging.getLogger("app.coding")
Applicant = require_role(UserRole.APPLICANT)
_busy_runs: set[uuid.UUID] = set()  # 세션당 동시에 하나의 실행만 (연타 방지 + 메모리 예산)


def _sandbox(request: Request):  # noqa: ANN202
    sb = request.app.state.services.sandbox
    if sb is None or not request.app.state.settings.sandbox_enabled:
        raise ApiError(503, "SANDBOX_DISABLED", "코딩테스트 실행 환경이 비활성화되어 있습니다")
    return sb


async def _ctx(db: AsyncSession, session_id: uuid.UUID, user: User) -> tuple[InterviewSession, JobPosting, Problem]:
    sess = await owned_session(db, session_id, user)
    app = await db.get(Application, sess.application_id)
    job = await db.get(JobPosting, app.job_id)
    if not job.coding_test_enabled:
        raise ApiError(404, "NOT_FOUND", "코딩테스트가 없는 공고입니다")
    return sess, job, pick_problem(sess.id)


def _case_out(c: CaseResult | dict) -> CaseOut:
    d = c if isinstance(c, dict) else c.__dict__
    return CaseOut(index=d["index"], verdict=d["verdict"], runtime_ms=d.get("runtime_ms", 0), visible=d.get("visible", False),
                   stdout=d.get("stdout", ""), stderr=d.get("stderr", ""), truncated=d.get("truncated", False))


TIME_GRACE_SEC = 30  # 클라이언트 자동 제출·네트워크 지연 여유


async def _elapsed_sec(db: AsyncSession, session_id: uuid.UUID) -> int | None:
    """코딩테스트 시작 시각 = 마지막 (코드 꼬리질문이 아닌) 질문의 답변이 끝난 시각. 세션에 별도 컬럼이 없어 턴 기록에서 유도한다."""
    last = (await db.execute(select(InterviewTurn.answer_ended_at).where(InterviewTurn.session_id == session_id, InterviewTurn.kind != TurnKind.CODE_FOLLOWUP,
                                                                        InterviewTurn.answer_ended_at.is_not(None)).order_by(InterviewTurn.turn_no.desc()).limit(1))).scalar_one_or_none()
    if last is None:
        return None
    return max(0, int((utcnow() - last).total_seconds()))


async def _enforce_time(db: AsyncSession, session_id: uuid.UUID, job: JobPosting) -> None:
    limit = job.coding_test_time_limit_sec
    elapsed = await _elapsed_sec(db, session_id) if limit else None
    if limit and elapsed is not None and elapsed > limit + TIME_GRACE_SEC:
        raise ApiError(409, "CODING_TIME_UP", "코딩테스트 제한시간이 끝났습니다", {"limit_sec": limit})


def _require_coding(sess: InterviewSession) -> None:
    if sess.state != SessionState.CODING:
        raise ApiError(409, "CODING_NOT_AVAILABLE", "모든 질문이 끝나야 코딩테스트를 시작할 수 있습니다", {"state": sess.state.value})


async def _existing(db: AsyncSession, session_id: uuid.UUID) -> CodeSubmission | None:
    return (await db.execute(select(CodeSubmission).where(CodeSubmission.session_id == session_id)
                             .order_by(CodeSubmission.submitted_at.desc()).limit(1))).scalar_one_or_none()


@router.get("/sessions/{session_id}/code/problem", response_model=ProblemOut)
async def get_problem_for_session(session_id: uuid.UUID, request: Request, user: User = Depends(Applicant), db: AsyncSession = Depends(get_db)) -> ProblemOut:
    _sandbox(request)
    sess, job, p = await _ctx(db, session_id, user)
    sub = await _existing(db, session_id)
    if sub is None:
        _require_coding(sess)
    s = request.app.state.settings
    return ProblemOut(problem_id=p.id, title=p.title, statement=p.statement, input_format=p.input_format, output_format=p.output_format,
                      constraints=p.constraints, examples=[ExampleOut(input=e.stdin, output=e.expected) for e in p.examples],
                      languages=[LanguageOut(id=k, label=v["label"], starter=STARTERS[k]) for k, v in LANGUAGES.items()],  # type: ignore[arg-type]
                      time_limit_sec=job.coding_test_time_limit_sec, exec_time_limit_sec=s.sandbox_time_limit_sec, memory_limit_mb=s.sandbox_memory_mb,
                      case_count=len(p.cases), submitted=sub is not None, elapsed_sec=await _elapsed_sec(db, session_id))


@router.post("/sessions/{session_id}/code/run", response_model=RunOut)
async def run_samples(session_id: uuid.UUID, body: CodeIn, request: Request, user: User = Depends(Applicant), db: AsyncSession = Depends(get_db)) -> RunOut:
    sandbox = _sandbox(request)
    sess, job, p = await _ctx(db, session_id, user)
    _require_coding(sess)
    if await _existing(db, session_id) is not None:
        raise ApiError(409, "CODE_ALREADY_SUBMITTED", "이미 제출했습니다")
    await _enforce_time(db, session_id, job)
    allowed, retry_after = request.app.state.code_run_limiter.hit(str(user.id))
    if not allowed:
        raise ApiError(429, "RATE_LIMITED", "실행 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요", {"retry_after_sec": retry_after}, headers={"Retry-After": str(retry_after)})
    if session_id in _busy_runs:
        raise ApiError(429, "RUN_IN_PROGRESS", "이전 실행이 끝나면 다시 실행할 수 있습니다")
    _busy_runs.add(session_id)
    try:
        j = await judge(sandbox, body.language, body.source, p.cases, visible=p.samples, time_limit_s=request.app.state.settings.sandbox_time_limit_sec,
                        limit_cases=p.samples)
    except SandboxUnavailable as e:
        raise ApiError(503, "SANDBOX_UNAVAILABLE", "실행 환경을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요") from e
    finally:
        _busy_runs.discard(session_id)
    return RunOut(verdict=j.verdict, cases=[_case_out(c) for c in j.cases], compile_log=j.compile_log)  # type: ignore[arg-type]


@router.post("/sessions/{session_id}/code/submit", response_model=SubmitAccepted, status_code=202)
async def submit_code(session_id: uuid.UUID, body: CodeIn, request: Request, user: User = Depends(Applicant), db: AsyncSession = Depends(get_db)) -> SubmitAccepted:
    sandbox = _sandbox(request)
    sess, job, p = await _ctx(db, session_id, user)
    _require_coding(sess)
    await _enforce_time(db, session_id, job)
    if await _existing(db, session_id) is not None:  # 제출은 한 번만 — 꼬리질문의 근거가 흔들리지 않게 한다
        raise ApiError(409, "CODE_ALREADY_SUBMITTED", "이미 제출했습니다")
    if len(body.source) > MAX_SOURCE_CHARS:
        raise ApiError(422, "VALIDATION_ERROR", "코드가 너무 깁니다")
    sub = CodeSubmission(session_id=session_id, language=body.language, source_code=body.source, submitted_at=utcnow())
    db.add(sub)
    await db.commit()
    sub_id = sub.id
    request.app.state.services.spawn(_judge_in_background(request.app, sandbox, sub_id, session_id, p, body.language, body.source), f"judge:{sub_id}")
    return SubmitAccepted(submission_id=sub_id)


async def _judge_in_background(app, sandbox, sub_id: uuid.UUID, session_id: uuid.UUID, p: Problem, language: str, source: str) -> None:  # noqa: ANN001
    from app.coding.analysis import analyze_source
    from app.interview.runtime import CodeContext

    settings = app.state.settings
    try:
        j = await judge(sandbox, language, source, p.cases, visible=p.samples, time_limit_s=settings.sandbox_time_limit_sec)
        analysis = await analyze_source(sandbox, language, source)
        results = [c.__dict__ for c in j.cases]
        async with app.state.sessionmaker() as db:
            sub = await db.get(CodeSubmission, sub_id)
            sub.verdict, sub.case_results, sub.runtime_ms, sub.static_analysis = Verdict(j.verdict), results, j.runtime_ms, analysis | ({"compile_log": j.compile_log} if j.compile_log else {})
            await db.commit()
    except SandboxUnavailable:
        async with app.state.sessionmaker() as db:  # 실행 환경 장애: 재제출할 수 있도록 제출을 되돌린다
            sub = await db.get(CodeSubmission, sub_id)
            if sub is not None:
                await db.delete(sub)
                await db.commit()
        log.warning("sandbox unavailable while judging")
        return
    except Exception as e:  # noqa: BLE001  소스·PII 는 기록하지 않는다
        log.warning("judge failed: %s", type(e).__name__)
        return
    rt = app.state.session_manager.get(session_id)
    if rt is not None:  # 제출 직후 코드 꼬리질문 (TRD §5.6)
        await rt.code_submitted(CodeContext(sub_id, p.title, p.statement, language, source, j.verdict, [c.verdict for c in j.cases], analysis))


@router.get("/sessions/{session_id}/code/result", response_model=ResultOut)
async def code_result(session_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ResultOut:
    if user.role == UserRole.APPLICANT:
        await owned_session(db, session_id, user)
        staff = False
    else:
        sess = (await db.execute(select(InterviewSession, JobPosting.company_id).join(Application, Application.id == InterviewSession.application_id)
                                 .join(JobPosting, JobPosting.id == Application.job_id).where(InterviewSession.id == session_id))).first()
        if sess is None or sess[1] != company_of(user) or user.role not in (UserRole.RECRUITER, UserRole.ADMIN):
            raise ApiError(404, "NOT_FOUND", "세션을 찾을 수 없습니다")
        staff = True
    sub = await _existing(db, session_id)
    if sub is None:
        return ResultOut(status="none")
    if sub.verdict is None:
        return ResultOut(status="judging", submission_id=sub.id, language=sub.language)
    cases = [_case_out(c) for c in (sub.case_results or [])]
    analysis = dict(sub.static_analysis or {})
    log_text = str(analysis.pop("compile_log", ""))
    if staff:
        db.add(AuditLog(user_id=user.id, action="view_code", target_type="session", target_id=session_id, ip=request.client.host if request.client else None))
        await db.commit()
    return ResultOut(status="done", submission_id=sub.id, language=sub.language, verdict=sub.verdict.value, runtime_ms=sub.runtime_ms, cases=cases, compile_log=log_text,
                     source_code=sub.source_code if staff else None, static_analysis=analysis if staff else None)


_ = (timezone, get_settings_dep)
