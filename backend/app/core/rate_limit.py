"""프로세스 내 슬라이딩 윈도 레이트 리미터 (TRD §8.3: 로그인 시도 5회/분).

단일 프로세스 배포(워커 1개, TRD §1.3) 전제. 다중 프로세스로 확장하면 공유 저장소로 교체해야 한다.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_sec: float, clock=time.monotonic):
        self.max_events, self.window, self._clock = max_events, window_sec, clock
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> tuple[bool, int]:
        """시도를 기록한다. (허용 여부, 거부 시 재시도까지 남은 초)."""
        now = self._clock()
        q = self._events[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.max_events:
            return False, max(1, int(self.window - (now - q[0])) + 1)
        q.append(now)
        if len(self._events) > 10_000:  # 메모리 상한: 오래된 키 정리
            self._purge(now)
        return True, 0

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._events.clear()
        else:
            self._events.pop(key, None)

    def _purge(self, now: float) -> None:
        for k in [k for k, q in self._events.items() if not q or now - q[-1] >= self.window]:
            del self._events[k]
