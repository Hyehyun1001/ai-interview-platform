"""미디어 채널 바이너리 프레임 (TRD §7.7): [1B type][4B seq(uint32 BE)][payload]. type 0x01 = 오디오 PCM16 16kHz mono, 0x02 = 영상 webm 청크."""
from __future__ import annotations

from dataclasses import dataclass

AUDIO = 0x01
VIDEO = 0x02
HEADER_BYTES = 5
MAX_AUDIO_PAYLOAD = 64 * 1024  # 500ms PCM16 청크 = 16,000 B 의 4배 여유
MAX_VIDEO_PAYLOAD = 2 * 1024 * 1024  # 5초 webm 슬라이스 (600kbps ≈ 375KB) 의 여유


class ProtocolError(Exception):
    pass


@dataclass(frozen=True)
class MediaFrame:
    type: int
    seq: int
    payload: bytes


def parse_frame(data: bytes) -> MediaFrame:
    if len(data) < HEADER_BYTES:
        raise ProtocolError("frame too short")
    ftype = data[0]
    if ftype not in (AUDIO, VIDEO):
        raise ProtocolError(f"unknown frame type {ftype:#x}")
    payload = data[HEADER_BYTES:]
    if len(payload) > (MAX_AUDIO_PAYLOAD if ftype == AUDIO else MAX_VIDEO_PAYLOAD):
        raise ProtocolError("payload too large")
    if ftype == AUDIO and len(payload) % 2:
        raise ProtocolError("PCM16 payload must have even length")
    return MediaFrame(ftype, int.from_bytes(data[1:5], "big"), payload)


def build_frame(ftype: int, seq: int, payload: bytes) -> bytes:
    """테스트·클라이언트 참조 구현."""
    return bytes([ftype]) + seq.to_bytes(4, "big") + payload
