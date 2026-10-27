"""면접 세션 REST 응답 (TRD §7.4)."""
from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.models.enums import SessionState, TurnKind


class WsTokenResponse(BaseModel):
    """채널별 1회용 단기 토큰 (control · media 각각 연결). 응답 형태는 TRD §7.4 에 정의가 없어 여기서 확정한다."""

    control_token: str
    media_token: str
    expires_in: int


class CurrentTurn(BaseModel):
    turn_id: uuid.UUID
    turn_no: int
    kind: TurnKind
    text: str
    remaining_sec: int | None = None  # 답변 중일 때만


class SessionStateResponse(BaseModel):
    session_id: uuid.UUID
    state: SessionState
    current_turn_no: int
    followup_count: int
    total_main: int
    degraded_mode: bool
    current_turn: CurrentTurn | None = None


class SessionCreated(BaseModel):
    session_id: uuid.UUID
    state: SessionState


class DeviceCheckIn(BaseModel):
    """사전 환경 점검 결과 (UI_SPEC APP-06). 영상·음성 원본은 보내지 않는다 — 통과 여부와 장치 이름만."""

    camera: bool
    mic: bool
    speaker: bool
    devices: dict[str, str] = {}


class DeviceCheckOut(BaseModel):
    all_ok: bool


class StartResponse(BaseModel):
    """`preparing`(이력서 인덱싱 중) → `warming`(모델 warm-up 중) → `ready`. 202 면 같은 엔드포인트를 다시 호출해 polling 한다."""

    status: str
    state: SessionState
    degraded_mode: bool = False


class FinishResponse(BaseModel):
    report_status: str
