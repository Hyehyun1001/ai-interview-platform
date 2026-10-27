"""STT 엔진 인터페이스 (TRD §4.2, §11 #1/#25). 엔진 교체(faster-whisper ↔ mlx-whisper)는 이 인터페이스 뒤에서만 일어난다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # PCM16 mono


@dataclass
class SttResult:
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None

    @property
    def low_confidence(self) -> bool:
        """STT 품질 신호 → stt_unclear 플래그 (꼬리질문 발동 조건, VOI-5)."""
        return (self.avg_logprob is not None and self.avg_logprob < -1.0) or (
            self.no_speech_prob is not None and self.no_speech_prob > 0.6) or not self.text.strip()


class STTEngine(Protocol):
    async def transcribe_pcm(self, pcm: bytes, *, initial_prompt: str | None = None) -> SttResult:
        """16kHz mono PCM16 바이트열을 한국어로 전사한다."""
        ...


def pcm_duration_ms(num_bytes: int) -> int:
    return num_bytes * 1000 // (SAMPLE_RATE * BYTES_PER_SAMPLE)
