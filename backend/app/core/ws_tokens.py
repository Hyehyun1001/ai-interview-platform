"""WebSocket 단기 토큰 (TRD §4.1): 60초 유효, 1회용, 채널(control/media)·세션·사용자에 묶인다.

REST `POST /sessions/{id}/ws-token` 로 발급하고, 연결 시 `?token=` 으로 제시한다. 쿼리스트링은 접근 로그에 남을 수 있으므로
수명을 짧게 하고 1회 사용 후 폐기한다.
"""
from __future__ import annotations

import time
import uuid
from datetime import timedelta
from typing import Literal

from app.core.errors import ApiError
from app.core.security import create_token_with_claims, decode_claims

Channel = Literal["control", "media"]


def issue_ws_token(secret: str, user_id: uuid.UUID, session_id: uuid.UUID, channel: Channel, ttl_sec: int) -> str:
    return create_token_with_claims(secret, user_id, "ws", timedelta(seconds=ttl_sec),
                                    {"sid": str(session_id), "ch": channel})


class WsTokenRegistry:
    """사용된 jti 를 만료 시각까지 기억해 재사용(리플레이)을 막는다. 단일 프로세스 전제 (TRD §1.3)."""

    def __init__(self, clock=time.time) -> None:
        self._used: dict[str, float] = {}
        self._clock = clock

    def consume(self, jti: str, exp_ts: float) -> bool:
        now = self._clock()
        for k in [k for k, e in self._used.items() if e < now]:
            del self._used[k]
        if jti in self._used:
            return False
        self._used[jti] = exp_ts
        return True


def verify_ws_token(secret: str, token: str, *, session_id: uuid.UUID, channel: Channel, registry: WsTokenRegistry) -> uuid.UUID:
    """서명·만료·세션·채널을 검증하고 1회용으로 소비한다. 성공 시 user_id. 실패 시 401 ApiError."""
    claims = decode_claims(secret, token, "ws")
    if claims.get("sid") != str(session_id) or claims.get("ch") != channel:
        raise ApiError(401, "UNAUTHORIZED", "인증이 필요합니다")
    if not registry.consume(claims["jti"], float(claims["exp"])):
        raise ApiError(401, "UNAUTHORIZED", "이미 사용된 토큰입니다")
    return uuid.UUID(claims["sub"])
