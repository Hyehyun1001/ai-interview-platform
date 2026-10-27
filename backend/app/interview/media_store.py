"""면접 미디어 파일 저장 (TRD §4.2/§4.3, NFR-Q2: 답변 오디오는 디스크에 즉시 append 하여 새로고침·단절에도 유실 최소화).

경로: {media_root}/{session_id}/{turn_id}.pcm, {media_root}/{session_id}/video.webm — 파일명은 UUID 만 사용(성명·원본명 미노출),
디렉터리 0700 / 파일 0600 (TRD §8.3). 미디어는 정적 서빙하지 않고 항상 API 를 경유한다.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from app.ai.stt.base import pcm_duration_ms

MAX_VIDEO_BYTES = 1024 * 1024 * 1024  # 세션당 영상 상한 (디스크 보호)


class AnswerRecording:
    def __init__(self, path: Path):
        self.path = path
        self._fh = open(path, "ab", buffering=0)  # noqa: SIM115  버퍼링 없이 즉시 기록
        os.chmod(path, 0o600)
        self.bytes_written = path.stat().st_size

    def append(self, pcm: bytes) -> None:
        self._fh.write(pcm)
        self.bytes_written += len(pcm)

    @property
    def duration_ms(self) -> int:
        return pcm_duration_ms(self.bytes_written)

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def read_all(self) -> bytes:
        return self.path.read_bytes()


class MediaStore:
    def __init__(self, root: Path):
        self.root = root

    def _session_dir(self, session_id: uuid.UUID) -> Path:
        d = self.root / str(session_id)
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        return d

    def open_answer(self, session_id: uuid.UUID, turn_id: uuid.UUID) -> AnswerRecording:
        return AnswerRecording(self._session_dir(session_id) / f"{turn_id}.pcm")

    def answer_path(self, session_id: uuid.UUID, turn_id: uuid.UUID) -> Path:
        return self._session_dir(session_id) / f"{turn_id}.pcm"

    def append_video(self, session_id: uuid.UUID, chunk: bytes) -> bool:
        """영상 청크를 이어 쓴다(재인코딩 없음). 상한을 넘으면 False."""
        path = self._session_dir(session_id) / "video.webm"
        if path.exists() and path.stat().st_size + len(chunk) > MAX_VIDEO_BYTES:
            return False
        with open(path, "ab") as fh:
            fh.write(chunk)
        os.chmod(path, 0o600)
        return True
