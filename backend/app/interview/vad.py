"""에너지 기반 VAD (침묵 종료·증분 STT 경계 판정용). TRD §4.2 의 webrtcvad/silero-vad 로 교체 가능한 최소 구현.

20ms 프레임의 RMS 가 임계값을 넘으면 발화로 본다. 반환값은 모두 "지금까지 누적된 밀리초"이다.
"""
from __future__ import annotations

import numpy as np

from app.ai.stt.base import BYTES_PER_SAMPLE, SAMPLE_RATE

FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * BYTES_PER_SAMPLE


class EnergyVad:
    def __init__(self, rms_threshold: float = 400.0):
        self.rms_threshold = rms_threshold
        self.speech_ms = 0  # 누적 발화 시간
        self.silence_run_ms = 0  # 마지막 발화 이후 연속 침묵
        self.has_speech = False
        self._rest = b""

    def feed(self, pcm: bytes) -> None:
        data = self._rest + pcm
        usable = len(data) - len(data) % FRAME_BYTES
        self._rest = data[usable:]
        if not usable:
            return
        frames = np.frombuffer(data[:usable], dtype=np.int16).reshape(-1, FRAME_BYTES // BYTES_PER_SAMPLE).astype(np.float32)
        rms = np.sqrt((frames ** 2).mean(axis=1))
        for loud in rms >= self.rms_threshold:
            if loud:
                self.has_speech = True
                self.speech_ms += FRAME_MS
                self.silence_run_ms = 0
            elif self.has_speech:
                self.silence_run_ms += FRAME_MS

    def reset_silence(self) -> None:
        self.silence_run_ms = 0
