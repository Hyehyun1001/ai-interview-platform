"""인증 라우터: POST /auth/register, /auth/login, /auth/refresh, /auth/logout, GET /me (TRD §7.1)."""
from __future__ import annotations

import logging
import shutil
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import ACCESS_COOKIE, REFRESH_COOKIE, get_current_user, get_db, get_settings_dep, require_role
from app.core.errors import ApiError
from app.core.security import create_token, decode_token, hash_password, needs_rehash, verify_password
from app.models.enums import SessionState, UserRole
from app.models.user import User
from app.schemas.auth import AuthResponse, DeleteAccountIn, LoginRequest, ProfileOut, ProfilePatch, RegisterRequest, UserOut

router = APIRouter(tags=["auth"])
log = logging.getLogger("app.auth")



def _invalid() -> ApiError:
    # 이메일/비밀번호/역할 중 무엇이 틀렸는지 구분하지 않는다 (UI_SPEC §4.1.1)
    return ApiError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다")


def _issue_session(response: Response, settings: Settings, user: User) -> AuthResponse:
    access_ttl = timedelta(minutes=settings.jwt_access_ttl_min)
    refresh_ttl = timedelta(days=settings.jwt_refresh_ttl_days)
    role = user.role.value
    access = create_token(settings.jwt_secret, user.id, role, "access", access_ttl)
    refresh = create_token(settings.jwt_secret, user.id, role, "refresh", refresh_ttl)
    common = {"httponly": True, "samesite": "lax", "secure": settings.is_prod}
    response.set_cookie(ACCESS_COOKIE, access, max_age=int(access_ttl.total_seconds()), path="/", **common)
    # refresh 쿠키는 인증 경로에만 전송되도록 제한
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=int(refresh_ttl.total_seconds()), path="/api/v1/auth", **common)
    return AuthResponse(user=UserOut.model_validate(user), access_token=access, expires_in=int(access_ttl.total_seconds()))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest, request: Request, response: Response,
                   db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep)) -> AuthResponse:
    """지원자 회원가입. 담당자(recruiter) 계정은 이 경로로 만들 수 없다. 가입 직후 자동 로그인(UI_SPEC §4.1.2)."""
    allowed, retry_after = request.app.state.register_limiter.hit(_client_ip(request))
    if not allowed:
        raise ApiError(429, "RATE_LIMITED", "가입 시도가 너무 많습니다. 잠시 후 다시 시도해주세요", {"retry_after_sec": retry_after}, headers={"Retry-After": str(retry_after)})
    exists = (await db.execute(select(User.id).where(User.email == body.email))).first()
    if exists:
        raise ApiError(409, "EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다", {"field": "email"})
    password_hash = await run_in_threadpool(hash_password, body.password)
    user = User(
        email=body.email, password_hash=password_hash, role=UserRole.APPLICANT, name=body.name,
        birth_date=body.birth_date.isoformat(), gender=body.gender.value, phone=body.phone,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as e:  # 동시 가입 경합: UNIQUE(email) 위반
        await db.rollback()
        raise ApiError(409, "EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다", {"field": "email"}) from e
    return _issue_session(response, settings, user)


@router.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request, response: Response,
                db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep)) -> AuthResponse:
    allowed, retry_after = request.app.state.login_limiter.hit(f"{_client_ip(request)}:{body.email}")
    if not allowed:
        raise ApiError(429, "RATE_LIMITED", "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요",
                       {"retry_after_sec": retry_after}, headers={"Retry-After": str(retry_after)})

    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    password_ok = await run_in_threadpool(verify_password, user.password_hash if user else None, body.password)
    if user is None or not password_ok or not body.role.accepts(user.role):
        raise _invalid()
    if not user.is_active:  # 자격 증명이 맞은 경우에만 비활성 사유를 알려준다
        raise ApiError(403, "ACCOUNT_DISABLED", "사용할 수 없는 계정입니다. 담당자에게 문의하세요")

    if needs_rehash(user.password_hash):  # argon2 파라미터 상향 시 점진 갱신
        user.password_hash = await run_in_threadpool(hash_password, body.password)
        await db.commit()
    return _issue_session(response, settings, user)


@router.post("/auth/refresh", response_model=AuthResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db),
                  settings: Settings = Depends(get_settings_dep)) -> AuthResponse:
    """refresh 쿠키로 access/refresh 를 재발급(회전). access 토큰으로는 호출할 수 없다."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise ApiError(401, "UNAUTHORIZED", "인증이 필요합니다")
    claims = decode_token(settings.jwt_secret, token, "refresh")
    user = (await db.execute(select(User).where(User.id == claims.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise ApiError(401, "UNAUTHORIZED", "인증이 필요합니다")
    return _issue_session(response, settings, user)


@router.post("/auth/logout", status_code=204)
async def logout(_user: User = Depends(get_current_user)) -> Response:
    """쿠키 삭제. refresh 토큰은 무상태(stateless)라 서버 측 폐기는 하지 않는다 (TRD에 폐기 저장소 없음)."""
    response = Response(status_code=204)
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return response


@router.get("/me", response_model=ProfileOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=ProfileOut)
async def patch_me(body: ProfilePatch, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    """이름·연락처 수정, 비밀번호 변경(현재 비밀번호 필수). 생년월일·성별은 수정할 수 없다."""
    user = await db.merge(user)
    if body.new_password is not None:
        if not await run_in_threadpool(verify_password, user.password_hash, body.current_password or ""):
            raise ApiError(422, "WRONG_PASSWORD", "현재 비밀번호가 일치하지 않습니다", {"field": "current_password"})
        user.password_hash = await run_in_threadpool(hash_password, body.new_password)
    if body.name is not None:
        user.name = body.name
    if body.phone is not None:
        user.phone = body.phone
    await db.commit()
    return user


@router.delete("/me", status_code=204)
async def delete_me(body: DeleteAccountIn, request: Request, user: User = Depends(require_role(UserRole.APPLICANT)),
                    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep)) -> Response:
    """계정·데이터 즉시 삭제 (NFR-S7, TRD §8.3). 비밀번호 재확인 필수. DB 행(FK CASCADE) + 미디어 파일 + 벡터 인덱스를 지운다."""
    if not await run_in_threadpool(verify_password, user.password_hash, body.password):
        raise ApiError(422, "WRONG_PASSWORD", "비밀번호가 일치하지 않습니다", {"field": "password"})
    from app.models import Application, InterviewSession

    rows = (await db.execute(select(InterviewSession.id, InterviewSession.state).join(Application, Application.id == InterviewSession.application_id)
                             .where(Application.user_id == user.id))).all()
    if any(st in (SessionState.IN_PROGRESS, SessionState.PAUSED, SessionState.CODING) for _sid, st in rows):
        raise ApiError(409, "SESSION_IN_PROGRESS", "진행 중인 면접이 있어 지금은 삭제할 수 없습니다")
    user_id, session_ids = user.id, [sid for sid, _ in rows]
    await db.delete(await db.merge(user))
    await db.commit()
    for sid in session_ids:  # 커밋 이후 파일·인덱스 정리 (실패해도 DB 삭제는 유지되며 고아 파일은 보관 정책 잡이 지운다)
        shutil.rmtree(settings.media_root / str(sid), ignore_errors=True)
    store = request.app.state.services.vector_store()
    if store is not None:
        try:
            await run_in_threadpool(store.delete_user, str(user_id))
        except Exception as e:  # noqa: BLE001  원문·PII 는 기록하지 않는다
            log.warning("vector delete_user failed: %s", type(e).__name__)
    response = Response(status_code=204)
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return response
