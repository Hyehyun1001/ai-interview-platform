"""세션 런타임 레지스트리 + 동시 세션 한도 (TRD §2.5: MAX_CONCURRENT_SESSIONS=1)."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.interview.runtime import Engines, SessionRuntime


class SlotUnavailable(Exception):
    """동시 면접 세션 한도 초과. 대기 안내(409 SESSION_SLOT_UNAVAILABLE)에 사용."""


class SessionManager:
    def __init__(self, sessionmaker: async_sessionmaker, engines: Engines, max_sessions: int = 1):
        self.sm, self.engines, self.max_sessions = sessionmaker, engines, max_sessions
        self._runtimes: dict[uuid.UUID, SessionRuntime] = {}

    def get(self, session_id: uuid.UUID) -> SessionRuntime | None:
        return self._runtimes.get(session_id)

    async def acquire(self, session_id: uuid.UUID, user_id: uuid.UUID,
                      on_release: Callable[[uuid.UUID], None] | None = None) -> SessionRuntime:
        """기존 런타임을 돌려주거나, 한도 내라면 새로 만들어 상태를 복원한다. paused 세션도 슬롯을 점유한다(만료 시 해제)."""
        if (rt := self._runtimes.get(session_id)) is not None:
            return rt
        if len(self._runtimes) >= self.max_sessions:
            raise SlotUnavailable
        rt = SessionRuntime(session_id, user_id, self.sm, self.engines, on_release=self._release)
        await rt.load()
        self._runtimes[session_id] = rt
        return rt

    def _release(self, session_id: uuid.UUID) -> None:
        self._runtimes.pop(session_id, None)

    async def discard(self, session_id: uuid.UUID) -> None:
        """세션을 끝내면서 런타임을 정리하고 슬롯을 반환한다. `aclose()` 만 부르면 레지스트리에 죽은 런타임이 남아 다음 지원자가 영원히 슬롯을 얻지 못한다."""
        rt = self._runtimes.pop(session_id, None)
        if rt is not None:
            await rt.aclose()

    async def shutdown(self) -> None:
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        for rt in runtimes:
            await rt.aclose()
