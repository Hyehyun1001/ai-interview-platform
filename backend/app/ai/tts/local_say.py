"""macOS `say` 오프라인 TTS (TRD §4.2 기본 엔진: macOS say Yuna). 외부 네트워크 호출 없음."""
from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

CHUNK_BYTES = 32 * 1024


class LocalSayTTS:
    format = "wav"

    def __init__(self, voice: str = "Yuna", timeout_s: float = 10.0):
        self.voice, self.timeout_s = voice, timeout_s

    async def _run(self, *argv: str) -> None:
        proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            if await asyncio.wait_for(proc.wait(), self.timeout_s) != 0:
                raise RuntimeError(f"{argv[0]} 실패")
        except asyncio.TimeoutError:
            proc.kill()
            raise

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        with tempfile.TemporaryDirectory(prefix="tts_") as tmp:
            aiff, wav = Path(tmp, "q.aiff"), Path(tmp, "q.wav")
            await self._run("say", "-v", self.voice, "-o", str(aiff), "--", text)
            await self._run("afconvert", "-f", "WAVE", "-d", "LEI16@22050", "-c", "1", str(aiff), str(wav))
            data = wav.read_bytes()
        for i in range(0, len(data), CHUNK_BYTES):
            yield data[i:i + CHUNK_BYTES]
