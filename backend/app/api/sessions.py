"""면접 세션 REST (TRD §7.4): POST /sessions/{id}/ws-token, GET /sessions/{id}/state. 본인 세션만 접근 (NFR-S6)."""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_db, get_settings_dep, require_role
from app.core.errors import ApiError
from app.core.ws_tokens import issue_ws_token
from app.interview.brain import DEFAULT_MAIN_COUNT
from app.models import Application, InterviewSession, InterviewTurn, ResumeSnapshot, User
from app.models.enums import SessionState, UserRole
from app.schemas.session import (CurrentTurn, DeviceCheckIn, DeviceCheckOut, FinishResponse, SessionCreated, SessionStateResponse,
                                 StartResponse, WsTokenResponse)
from app.services.sessions import finalize_session, prep_done, prepare_session, warm_up

router = APIRouter(tags=["sessions"])
WS_ALLOWED = (SessionState.READY, SessionState.IN_PROGRESS, SessionState.PAUSED, SessionState.CODING)


async def owned_session(db: AsyncSession, session_id: uuid.UUID, user: User) -> InterviewSession:
    """본인 세션이 아니면 존재 여부를 숨기기 위해 404 (TRD §8.3 RBAC, V-8)."""
    row = (await db.execute(select(InterviewSession).join(Application, Application.id == InterviewSession.application_id)
                            .where(InterviewSession.id == session_id, Application.user_id == user.id))).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "세션을 찾을 수 없습니다")
    return row


@router.post("/sessions/{session_id}/ws-token", response_model=WsTokenResponse)
async def create_ws_token(session_id: uuid.UUID, user: User = Depends(require_role(UserRole.APPLICANT)),
                          db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep)) -> WsTokenResponse:
    sess = await owned_session(db, session_id, user)
    if sess.state not in WS_ALLOWED:
        raise ApiError(409, "SESSION_NOT_ACTIVE", "면접을 시작할 수 있는 상태가 아닙니다", {"state": sess.state.value})
    ttl = settings.ws_token_ttl_sec
    return WsTokenResponse(
        control_token=issue_ws_token(settings.jwt_secret, user.id, session_id, "control", ttl),
        media_token=issue_ws_token(settings.jwt_secret, user.id, session_id, "media", ttl), expires_in=ttl)


@router.get("/sessions/{session_id}/state", response_model=SessionStateResponse)
async def get_state(session_id: uuid.UUID, request: Request, user: User = Depends(require_role(UserRole.APPLICANT)),
                    db: AsyncSession = Depends(get_db)) -> SessionStateResponse:
    """새로고침 복구용 현재 상태 (TRD §4.5). 서버 재시작 후에도 DB 가 단일 진실 원천이다."""
    sess = await owned_session(db, session_id, user)
    last = (await db.execute(select(InterviewTurn).where(InterviewTurn.session_id == session_id)
                             .order_by(InterviewTurn.turn_no.desc()).limit(1))).scalar_one_or_none()
    total = len((sess.precomputed_context or {}).get("slots") or []) or DEFAULT_MAIN_COUNT
    current = None
    if last is not None and last.answer_ended_at is None:
        remaining = None
        rt = request.app.state.session_manager.get(session_id)
        if rt is not None and rt.turn is not None and rt.turn.started_mono is not None:
            remaining = max(0, int(rt.turn.time_limit_sec * rt.eng.tuning.timeout_scale - (time.monotonic() - rt.turn.started_mono)))
        current = CurrentTurn(turn_id=last.id, turn_no=last.turn_no, kind=last.kind, text=last.question_text, remaining_sec=remaining)
    return SessionStateResponse(session_id=session_id, state=sess.state, current_turn_no=sess.current_turn_no,
                                followup_count=sess.followup_count, total_main=total, degraded_mode=sess.degraded_mode,
                                current_turn=current)


SLOT_RETRY_AFTER_SEC = 30


@router.post("/applications/{application_id}/session", response_model=SessionCreated, status_code=201)
async def create_session(application_id: uuid.UUID, request: Request, response: Response, user: User = Depends(require_role(UserRole.APPLICANT)),
                         db: AsyncSession = Depends(get_db)) -> SessionCreated:
    """세션 생성 (조건: 동의 완료 + 스냅샷 기본정보 충족, 아니면 409). 이력서 인덱싱·질문 사전 검색을 백그라운드로 시작한다."""
    app = (await db.execute(select(Application).where(Application.id == application_id, Application.user_id == user.id))).scalar_one_or_none()
    if app is None:
        raise ApiError(404, "NOT_FOUND", "지원 내역을 찾을 수 없습니다")
    existing = (await db.execute(select(InterviewSession).where(InterviewSession.application_id == app.id))).scalar_one_or_none()
    if existing is not None:  # 멱등: 이미 만든 세션을 돌려준다 (새로고침·중복 클릭)
        response.status_code = 200
        return SessionCreated(session_id=existing.id, state=existing.state)
    if app.consent_at is None:
        raise ApiError(409, "CONSENT_REQUIRED", "개인정보 수집·이용 동의가 필요합니다")
    snap = (await db.execute(select(ResumeSnapshot).where(ResumeSnapshot.application_id == app.id))).scalar_one_or_none()
    if snap is None:
        raise ApiError(409, "BASIC_INFO_REQUIRED", "지원용 이력서를 먼저 확정해 주세요")
    sess = InterviewSession(application_id=app.id, state=SessionState.CREATED)
    db.add(sess)
    await db.commit()
    svc = request.app.state.services
    svc.spawn(prepare_session(svc, request.app.state.sessionmaker, sess.id, request.app.state.settings.interview_main_count), f"prep:{sess.id}")
    return SessionCreated(session_id=sess.id, state=sess.state)


@router.post("/sessions/{session_id}/device-check", response_model=DeviceCheckOut)
async def device_check(session_id: uuid.UUID, body: DeviceCheckIn, user: User = Depends(require_role(UserRole.APPLICANT)),
                       db: AsyncSession = Depends(get_db)) -> DeviceCheckOut:
    sess = await owned_session(db, session_id, user)
    if sess.state not in (SessionState.CREATED, SessionState.READY):
        raise ApiError(409, "SESSION_NOT_ACTIVE", "장치 점검을 할 수 없는 상태입니다", {"state": sess.state.value})
    ok = body.camera and body.mic and body.speaker
    sess.device_info = {**body.model_dump(), "all_ok": ok}
    await db.commit()
    return DeviceCheckOut(all_ok=ok)


@router.post("/sessions/{session_id}/start", response_model=StartResponse, responses={202: {"model": StartResponse}})
async def start_session(session_id: uuid.UUID, request: Request, response: Response, user: User = Depends(require_role(UserRole.APPLICANT)),
                        db: AsyncSession = Depends(get_db)) -> StartResponse:
    """모든 장치 정상 시 시작. 준비/warm-up 중이면 202 와 단계(`preparing`/`warming`)를 돌려주고, 같은 호출을 반복해 polling 한다."""
    sess = await owned_session(db, session_id, user)
    if sess.state in (SessionState.IN_PROGRESS, SessionState.PAUSED, SessionState.CODING):
        return StartResponse(status="ready", state=sess.state, degraded_mode=sess.degraded_mode)
    if sess.state not in (SessionState.CREATED, SessionState.READY):
        raise ApiError(409, "SESSION_NOT_ACTIVE", "이미 종료되었거나 시작할 수 없는 면접입니다", {"state": sess.state.value})
    if not (sess.device_info or {}).get("all_ok"):
        raise ApiError(409, "DEVICE_CHECK_REQUIRED", "카메라·마이크·스피커 점검을 먼저 완료해 주세요")
    manager = request.app.state.session_manager
    if manager.get(session_id) is None and len(manager._runtimes) >= manager.max_sessions:  # noqa: SLF001  동시 면접 한도 (TRD §2.5)
        raise ApiError(409, "SESSION_SLOT_UNAVAILABLE", "현재 다른 지원자가 면접 중입니다. 잠시 후 다시 시도해 주세요",
                       {"retry_after_sec": SLOT_RETRY_AFTER_SEC})
    if not prep_done(sess):
        response.status_code = 202
        return StartResponse(status="preparing", state=sess.state)
    svc = request.app.state.services
    if sess.state == SessionState.READY or svc.warmups.get(session_id) == "done":
        return StartResponse(status="ready", state=SessionState.READY, degraded_mode=sess.degraded_mode)
    if session_id not in svc.warmups:
        svc.warmups[session_id] = "warming"
        svc.spawn(warm_up(svc, manager.engines, request.app.state.sessionmaker, session_id), f"warmup:{session_id}")
    response.status_code = 202
    return StartResponse(status="warming", state=sess.state)


@router.post("/sessions/{session_id}/finish", response_model=FinishResponse, status_code=202)
async def finish_session(session_id: uuid.UUID, request: Request, user: User = Depends(require_role(UserRole.APPLICANT)),
                         db: AsyncSession = Depends(get_db)) -> FinishResponse:
    """종료 → 리포트 잡 enqueue (멱등). 면접이 시작되지 않았거나 중단된 세션은 409."""
    sess = await owned_session(db, session_id, user)
    if sess.state in (SessionState.CREATED, SessionState.READY, SessionState.ABORTED):
        raise ApiError(409, "SESSION_NOT_ACTIVE", "종료할 수 있는 상태가 아닙니다", {"state": sess.state.value})
    await request.app.state.session_manager.discard(session_id)  # 진행 중 런타임이 남아 있으면 정리하고 슬롯을 반환한다
    status = await finalize_session(request.app.state.sessionmaker, session_id)
    return FinishResponse(report_status=status.value)
