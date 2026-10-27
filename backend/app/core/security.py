"""비밀번호 해시(argon2id)와 JWT (TRD §1.1, §8.3). access 15분 + refresh 7일."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import ApiError

_ph = PasswordHasher()  # argon2id 기본 파라미터
ALGORITHM = "HS256"
TokenKind = Literal["access", "refresh", "ws"]

# 존재하지 않는 계정에도 동일한 해시 검증 비용을 들여 응답 시간으로 계정 존재 여부를 추측하지 못하게 한다
_DUMMY_HASH = _ph.hash("dummy-password-for-timing-equalization")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    role: str
    kind: TokenKind
    jti: str
    expires_at: datetime


def create_token(secret: str, user_id: uuid.UUID, role: str, kind: TokenKind, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "type": kind, "jti": uuid.uuid4().hex,
               "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp())}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(secret: str, token: str, expected: TokenKind) -> TokenClaims:
    """서명·만료·타입을 검증한다. 실패 시 401 ApiError (원인은 응답에 구분해 노출하지 않는다)."""
    try:
        data = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "iat", "sub", "type", "jti"]})
        if data["type"] != expected:
            raise jwt.InvalidTokenError("wrong token type")
        return TokenClaims(uuid.UUID(data["sub"]), data.get("role", ""), data["type"], data["jti"],
                           datetime.fromtimestamp(data["exp"], tz=timezone.utc))
    except (jwt.InvalidTokenError, ValueError, KeyError) as e:
        raise ApiError(401, "UNAUTHORIZED", "인증이 필요합니다", headers={"WWW-Authenticate": "Bearer"}) from e


def create_token_with_claims(secret: str, user_id: uuid.UUID, kind: TokenKind, ttl: timedelta, extra: dict) -> str:
    """추가 클레임(sid, ch 등)을 가진 토큰. WS 단기 토큰에 사용."""
    now = datetime.now(timezone.utc)
    payload = {**extra, "sub": str(user_id), "type": kind, "jti": uuid.uuid4().hex,
               "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp())}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_claims(secret: str, token: str, expected: TokenKind) -> dict:
    """원본 클레임 딕셔너리를 반환 (타입·서명·만료 검증은 decode_token 과 동일)."""
    try:
        data = jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "iat", "sub", "type", "jti"]})
        if data["type"] != expected:
            raise jwt.InvalidTokenError("wrong token type")
        return data
    except (jwt.InvalidTokenError, KeyError) as e:
        raise ApiError(401, "UNAUTHORIZED", "인증이 필요합니다", headers={"WWW-Authenticate": "Bearer"}) from e
