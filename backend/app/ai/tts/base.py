"""TTS 엔진 인터페이스 (TRD §4.2). 기본은 오프라인 엔진이며 외부 호출 엔진(edge-tts)은 opt-in 이다 (TRD §0 T-2)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class TTSEngine(Protocol):
    format: str  # "wav" | "mp3"

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """텍스트 → 오디오 청크 스트림. 실패 시 예외를 던진다(호출자가 자막 전용으로 복구)."""
        ...
