"""FastAPI 의존성: DB 세션, 현재 사용자, 역할 검사 (TRD §8.3 RBAC)."""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import decode_token
from app.models.enums import UserRole
from app.models.user import User

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def _access_token_from(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(ACCESS_COOKIE)


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = _access_token_from(request)
    if not token:
        raise ApiError(401, "UNAUTHORIZED", "인증이 필요합니다", headers={"WWW-Authenticate": "Bearer"})
    claims = decode_token(request.app.state.settings.jwt_secret, token, "access")
    user = (await db.execute(select(User).where(User.id == claims.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:  # 토큰 발급 후 비활성화/삭제된 계정은 즉시 차단
        raise ApiError(401, "UNAUTHORIZED", "인증이 필요합니다", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_role(*roles: UserRole) -> Callable[..., User]:
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ApiError(403, "FORBIDDEN", "권한이 없습니다")
        return user

    return _dep
