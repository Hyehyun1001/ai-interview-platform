"""WebSocket 제어 채널 메시지 (TRD §7.7). 모든 메시지: {"type", "seq", "ts", ...}.

C→S 메시지는 Pydantic discriminated union 으로 검증하고(알 수 없는 type·필드는 거부), S→C 메시지는 `server_message()` 로 만든다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.models.enums import GazeKind

MAX_TEXT_ANSWER_CHARS = 2000


class _Client(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int | None = Field(default=None, ge=0)  # 있으면 중복/역순 메시지를 무시하는 데 사용
    ts: str | None = None


class TtsDone(_Client):
    type: Literal["tts_done"]
    turn_id: uuid.UUID


class AnswerStart(_Client):
    type: Literal["answer_start"]
    turn_id: uuid.UUID


class AnswerEnd(_Client):
    type: Literal["answer_end"]
    turn_id: uuid.UUID
    reason: Literal["user", "timeout"]


class TextAnswer(_Client):
    """코드 꼬리질문(kind=code_followup) 전용 텍스트 답변 (TRD §7.7)."""

    type: Literal["text_answer"]
    turn_id: uuid.UUID
    text: str = Field(max_length=MAX_TEXT_ANSWER_CHARS)


class GazeEventMsg(_Client):
    type: Literal["gaze_event"]
    turn_id: uuid.UUID
    kind: GazeKind
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    yaw: float | None = None
    pitch: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ResumeMsg(_Client):
    type: Literal["resume"]
    last_turn_id: uuid.UUID | None = None


class Ping(_Client):
    type: Literal["ping"]


class Pong(_Client):
    type: Literal["pong"]


ClientMessage = Annotated[
    TtsDone | AnswerStart | AnswerEnd | TextAnswer | GazeEventMsg | ResumeMsg | Ping | Pong, Field(discriminator="type")]
CLIENT_ADAPTER: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)

SERVER_TYPES = {
    "session_ready", "question", "tts_chunk", "countdown", "stt_partial", "thinking", "stt_final", "gaze_warning",
    "degraded", "error", "session_finished", "ack", "ping", "pong",
}


def server_message(msg_type: str, seq: int, **payload: Any) -> dict[str, Any]:
    if msg_type not in SERVER_TYPES:
        raise ValueError(f"unknown server message type: {msg_type}")
    if {"type", "seq", "ts"} & payload.keys():
        raise ValueError("payload must not redefine envelope keys (type, seq, ts)")
    return {"type": msg_type, "seq": seq, "ts": datetime.now(timezone.utc).isoformat(), **payload}


# WebSocket close codes (애플리케이션 영역 4000~4999)
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_IDLE_TIMEOUT = 4408
CLOSE_CONFLICT = 4409  # 다른 연결이 이미 있음 / control 미연결 / 동시 세션 한도
CLOSE_PROTOCOL = 4400
