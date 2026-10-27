"""백그라운드 청크 증분 STT (TRD §2.4/§4.2 — 필수).

Whisper 는 입력 길이와 무관하게 호출당 고정 인코더 비용(CPU turbo ≈ 4s)이 들고, 60초 답변을 끝난 뒤 통째로 디코딩하면 ≈ 14s 가
걸려 E2E 목표를 달성할 수 없다. 그래서 답변이 진행되는 동안 확정된 구간(침묵 경계 또는 최대 길이)을 미리 디코딩해 두고,
답변 종료 시에는 마지막 미확정 구간 1회만 디코딩한다.

경계 규칙: 미확정 오디오가 MIN_CHUNK_MS 이상이고 연속 침묵이 BOUNDARY_SILENCE_MS 이상이면 확정, MAX_CHUNK_MS 에 도달하면 강제 확정.
(구간 경계에서 단어가 잘리는 품질 저하는 실제 음성으로 검증이 필요하다.)
"""
from __future__ import annotations

import asyncio

from app.ai.stt.base import STTEngine, SttResult, pcm_duration_ms
from app.interview.vad import EnergyVad

MIN_CHUNK_MS = 8_000
MAX_CHUNK_MS = 25_000
BOUNDARY_SILENCE_MS = 400
MIN_TAIL_MS = 300


class IncrementalStt:
    def __init__(self, engine: STTEngine, *, initial_prompt: str | None = None, min_chunk_ms: int = MIN_CHUNK_MS,
                 max_chunk_ms: int = MAX_CHUNK_MS, boundary_silence_ms: int = BOUNDARY_SILENCE_MS):
        self.engine, self.initial_prompt = engine, initial_prompt
        self.min_chunk_ms, self.max_chunk_ms, self.boundary_silence_ms = min_chunk_ms, max_chunk_ms, boundary_silence_ms
        self._pending = bytearray()  # 아직 디코딩하지 않은 오디오
        self._tasks: list[asyncio.Task[SttResult]] = []  # 확정 구간별 디코딩 (순서 유지)
        self.chunks_dispatched = 0

    def feed(self, pcm: bytes, vad: EnergyVad) -> None:
        """오디오와 VAD 상태를 받아 필요하면 확정 구간 디코딩을 백그라운드로 시작한다."""
        self._pending.extend(pcm)
        pending_ms = pcm_duration_ms(len(self._pending))
        at_silence = pending_ms >= self.min_chunk_ms and vad.silence_run_ms >= self.boundary_silence_ms
        if at_silence or pending_ms >= self.max_chunk_ms:
            self._dispatch()

    def _dispatch(self) -> None:
        chunk, self._pending = bytes(self._pending), bytearray()
        self.chunks_dispatched += 1
        self._tasks.append(asyncio.create_task(self.engine.transcribe_pcm(chunk, initial_prompt=self.initial_prompt)))

    async def finish(self) -> SttResult:
        """남은 구간 1회만 디코딩하고 앞선 구간 결과와 합친다. 한 구간이라도 실패하면 예외를 그대로 올린다."""
        if self._pending and (pcm_duration_ms(len(self._pending)) >= MIN_TAIL_MS or not self._tasks):
            self._dispatch()  # 300ms 미만의 꼬리 조각은 비용 대비 의미가 없어 건너뛴다 (전체가 짧은 경우는 예외)
        results = await asyncio.gather(*self._tasks)
        self._tasks = []
        texts = [r.text.strip() for r in results if r.text.strip()]
        lps = [r.avg_logprob for r in results if r.avg_logprob is not None]
        nss = [r.no_speech_prob for r in results if r.no_speech_prob is not None]
        return SttResult(" ".join(texts), sum(lps) / len(lps) if lps else None, max(nss) if nss else None)

    def cancel(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks = []
