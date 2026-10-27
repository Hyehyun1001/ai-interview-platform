"""오디오 스트리밍 (TRD §7.4). 서버에는 원시 PCM(16kHz mono s16le)이 저장되어 있으므로 WAV 헤더를 즉석에서 붙여 Range 요청을 지원한다.
파일 경로는 노출하지 않고 항상 이 API 를 경유하며, 담당자 재생은 감사 로그에 남긴다 (TRD §8.3)."""
from __future__ import annotations

import re
import struct
import uuid
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.errors import ApiError
from app.models import Application, AuditLog, InterviewSession, InterviewTurn, JobPosting, User
from app.models.enums import UserRole

router = APIRouter(tags=["media"])
SAMPLE_RATE, CHANNELS, BYTES_PER_SAMPLE = 16_000, 1, 2
CHUNK = 64 * 1024


def wav_header(pcm_len: int) -> bytes:
    byte_rate = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE
    return (b"RIFF" + struct.pack("<I", 36 + pcm_len) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, CHANNELS, SAMPLE_RATE, byte_rate, CHANNELS * BYTES_PER_SAMPLE, 16)
            + b"data" + struct.pack("<I", pcm_len))


def parse_range(header: str | None, total: int) -> tuple[int, int] | None:
    """`bytes=a-b` / `bytes=a-` / `bytes=-n` → (start, end) 포함 구간. 형식 오류는 None(전체 응답), 범위 밖은 ValueError(416)."""
    if not header:
        return None
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not m or (m[1] == "" and m[2] == ""):
        return None
    if m[1] == "":
        n = int(m[2])
        if n == 0:
            raise ValueError
        return max(0, total - n), total - 1
    start = int(m[1])
    end = min(int(m[2]), total - 1) if m[2] else total - 1
    if start >= total or end < start:
        raise ValueError
    return start, end


def iter_range(path: Path, header: bytes, start: int, end: int) -> Iterator[bytes]:
    """가상 파일 [header | pcm] 의 start..end 바이트."""
    pos = start
    if pos < len(header):
        take = min(end + 1, len(header)) - pos
        yield header[pos:pos + take]
        pos += take
    if pos <= end:
        with open(path, "rb") as fh:
            fh.seek(pos - len(header))
            remaining = end - pos + 1
            while remaining > 0:
                data = fh.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data


@router.get("/media/turns/{turn_id}/audio")
async def turn_audio(turn_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    row = (await db.execute(select(InterviewTurn, InterviewSession, Application, JobPosting.company_id)
                            .join(InterviewSession, InterviewSession.id == InterviewTurn.session_id)
                            .join(Application, Application.id == InterviewSession.application_id)
                            .join(JobPosting, JobPosting.id == Application.job_id).where(InterviewTurn.id == turn_id))).first()
    allowed = False
    if row is not None:
        _t, _s, app, company_id = row
        allowed = app.user_id == user.id if user.role == UserRole.APPLICANT else (user.company_id is not None and user.company_id == company_id)
    if not allowed:
        raise ApiError(404, "NOT_FOUND", "음성을 찾을 수 없습니다")
    turn, sess, app, _ = row
    path = request.app.state.session_manager.engines.media.answer_path(sess.id, turn.id)
    if not path.exists() or path.stat().st_size == 0:
        raise ApiError(404, "NOT_FOUND", "음성을 찾을 수 없습니다")
    pcm_len = path.stat().st_size - path.stat().st_size % (CHANNELS * BYTES_PER_SAMPLE)
    header = wav_header(pcm_len)
    total = len(header) + pcm_len
    try:
        rng = parse_range(request.headers.get("range"), total)
    except ValueError:
        return StreamingResponse(iter(()), status_code=416, headers={"Content-Range": f"bytes */{total}"})
    start, end = rng if rng else (0, total - 1)
    if user.role != UserRole.APPLICANT and start == 0:  # 재생 시작 시에만 기록 (구간 탐색마다 쌓이지 않게)
        db.add(AuditLog(user_id=user.id, action="play_audio", target_type="turn", target_id=turn.id, ip=request.client.host if request.client else None))
        await db.commit()
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Cache-Control": "private, no-store"}
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return StreamingResponse(iter_range(path, header, start, end), status_code=206 if rng else 200, media_type="audio/wav", headers=headers)
