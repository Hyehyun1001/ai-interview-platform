"""faster-whisper STT 어댑터 (M0 확정: large-v3-turbo, int8 CPU, cpu_threads=6). 모델은 첫 호출 시 지연 로딩한다."""
from __future__ import annotations

import asyncio

import numpy as np

from app.ai.stt.base import SttResult


class FasterWhisperSTT:
    def __init__(self, model: str = "large-v3-turbo", compute_type: str = "int8", cpu_threads: int = 6, beam_size: int = 1):
        self.model_name, self.compute_type, self.cpu_threads, self.beam_size = model, compute_type, cpu_threads, beam_size
        self._model = None
        self._lock = asyncio.Lock()  # CPU 추론은 한 번에 하나만 (메모리·지연 예산, NFR-R1)

    def _load(self):  # noqa: ANN202
        if self._model is None:
            from faster_whisper import WhisperModel  # 무거운 의존성: requirements-ai.txt

            self._model = WhisperModel(self.model_name, device="cpu", compute_type=self.compute_type, cpu_threads=self.cpu_threads)
        return self._model

    def _run(self, pcm: bytes, initial_prompt: str | None) -> SttResult:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._load().transcribe(
            audio, language="ko", beam_size=self.beam_size, vad_filter=True, condition_on_previous_text=False,
            word_timestamps=True, initial_prompt=initial_prompt)
        segs = list(segments)  # generator 소비
        text = " ".join(s.text.strip() for s in segs).strip()
        lp = [s.avg_logprob for s in segs if s.avg_logprob is not None]
        ns = [s.no_speech_prob for s in segs if s.no_speech_prob is not None]
        return SttResult(text, sum(lp) / len(lp) if lp else None, sum(ns) / len(ns) if ns else None)

    async def transcribe_pcm(self, pcm: bytes, *, initial_prompt: str | None = None) -> SttResult:
        async with self._lock:
            return await asyncio.to_thread(self._run, pcm, initial_prompt)

    def unload(self) -> None:
        self._model = None
