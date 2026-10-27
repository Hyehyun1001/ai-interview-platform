"""WebSocket 채널 (TRD §4.1, §7.7): /ws/sessions/{id}/control (JSON 양방향) · /ws/sessions/{id}/media (클라이언트→서버 바이너리).

인증: `?token=` 1회용 단기 토큰(채널·세션에 묶임). 핸드셰이크 후 검증하여 애플리케이션 close code(4401 등)로 사유를 전달한다.
세션당 연결은 control 1 + media 1. media 는 control 이 연결된 상태에서만 허용한다.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket
from sqlalchemy import select

from app.core.errors import ApiError
from app.core.ws_tokens import Channel, verify_ws_token
from app.interview import protocol
from app.interview.manager import SlotUnavailable
from app.models import Application, InterviewSession, User
from app.models.enums import SessionState
from app.schemas.ws import (CLOSE_CONFLICT, CLOSE_FORBIDDEN, CLOSE_IDLE_TIMEOUT, CLOSE_NOT_FOUND, CLOSE_PROTOCOL,
                            CLOSE_UNAUTHORIZED, server_message)

router = APIRouter()
log = logging.getLogger("app.ws")

ACTIVE_STATES = (SessionState.READY, SessionState.IN_PROGRESS, SessionState.PAUSED, SessionState.CODING)
MAX_TEXT_FRAME = 64 * 1024
ACK_EVERY = 5  # 5청크마다 ack (TRD §7.7)


async def _reject(ws: WebSocket, code: int, error_code: str, message: str) -> None:
    try:
        await ws.send_json(server_message("error", 0, code=error_code, recoverable=False, message=message))
        await ws.close(code=code)
    except Exception:  # noqa: BLE001  이미 끊긴 연결
        pass


async def _authenticate(ws: WebSocket, session_id: uuid.UUID, channel: Channel) -> uuid.UUID | None:
    """accept 후 토큰·소유권·세션 상태를 검증. 실패하면 사유 코드로 닫고 None."""
    await ws.accept()
    app = ws.app
    token = ws.query_params.get("token")
    if not token:
        await _reject(ws, CLOSE_UNAUTHORIZED, "UNAUTHORIZED", "인증이 필요합니다")
        return None
    try:
        user_id = verify_ws_token(app.state.settings.jwt_secret, token, session_id=session_id, channel=channel,
                                  registry=app.state.ws_registry)
    except ApiError:
        await _reject(ws, CLOSE_UNAUTHORIZED, "UNAUTHORIZED", "인증이 필요합니다")
        return None
    async with app.state.sessionmaker() as db:
        row = (await db.execute(select(InterviewSession, Application.user_id, User.is_active)
                                .join(Application, Application.id == InterviewSession.application_id)
                                .join(User, User.id == Application.user_id)
                                .where(InterviewSession.id == session_id))).first()
    if row is None:
        await _reject(ws, CLOSE_NOT_FOUND, "NOT_FOUND", "세션을 찾을 수 없습니다")
        return None
    sess, owner_id, active = row
    if owner_id != user_id or not active:
        await _reject(ws, CLOSE_FORBIDDEN, "FORBIDDEN", "권한이 없습니다")
        return None
    if sess.state not in ACTIVE_STATES:
        await _reject(ws, CLOSE_CONFLICT, "SESSION_NOT_ACTIVE", "진행할 수 없는 면접 상태입니다")
        return None
    return user_id


async def _keepalive(ws: WebSocket, rt, interval: float, last_seen: list[float]) -> None:
    """15초 주기 ping, 3주기(≈45초) 동안 아무 메시지도 없으면 끊는다 (TRD §7.7)."""
    while True:
        await asyncio.sleep(interval)
        if time.monotonic() - last_seen[0] > interval * 3:
            await ws.close(code=CLOSE_IDLE_TIMEOUT)
            return
        await rt.send("ping")


@router.websocket("/ws/sessions/{session_id}/control")
async def control_channel(ws: WebSocket, session_id: uuid.UUID) -> None:
    user_id = await _authenticate(ws, session_id, "control")
    if user_id is None:
        return
    manager = ws.app.state.session_manager
    try:
        rt = await manager.acquire(session_id, user_id)
    except SlotUnavailable:  # 동시 세션 한도 (MAX_CONCURRENT_SESSIONS=1): 클라이언트는 30초 뒤 재시도 (TRD §11 #14)
        await _reject(ws, CLOSE_CONFLICT, "SESSION_SLOT_UNAVAILABLE", "현재 다른 지원자가 면접 중입니다. 잠시 후 다시 시도해 주세요")
        return
    if rt.ws is not None:  # 다른 창에서 이미 진행 중
        await _reject(ws, CLOSE_CONFLICT, "ALREADY_CONNECTED", "다른 창에서 면접이 진행 중입니다")
        return

    last_seen = [time.monotonic()]
    keepalive = asyncio.create_task(_keepalive(ws, rt, rt.eng.tuning.ping_interval_s, last_seen))
    try:
        await rt.attach(ws)
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            last_seen[0] = time.monotonic()
            text = message.get("text")
            if text is None or len(text) > MAX_TEXT_FRAME:
                await rt.error("BAD_MESSAGE", "올바르지 않은 메시지입니다", recoverable=True)
                continue
            await rt.handle_text(text)
    except Exception as e:  # noqa: BLE001
        log.info("control channel closed: %s", type(e).__name__)
    finally:
        keepalive.cancel()
        await rt.detach(ws)


@router.websocket("/ws/sessions/{session_id}/media")
async def media_channel(ws: WebSocket, session_id: uuid.UUID) -> None:
    user_id = await _authenticate(ws, session_id, "media")
    if user_id is None:
        return
    rt = ws.app.state.session_manager.get(session_id)
    if rt is None or rt.ws is None or rt.user_id != user_id:  # control 채널이 먼저 연결되어 있어야 한다
        await _reject(ws, CLOSE_CONFLICT, "CONTROL_REQUIRED", "제어 채널이 먼저 연결되어야 합니다")
        return
    highest, received, missing = -1, 0, 0
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is None:
                await ws.close(code=CLOSE_PROTOCOL)
                return
            try:
                frame = protocol.parse_frame(data)
            except protocol.ProtocolError:
                await ws.close(code=CLOSE_PROTOCOL)
                return
            if frame.seq <= highest:  # 재전송된 중복 청크
                continue
            if highest >= 0 and frame.seq != highest + 1:
                missing += frame.seq - highest - 1  # 손실 감지 — ack 로 클라이언트에 알린다
            highest = frame.seq
            if frame.type == protocol.AUDIO:
                rt.on_audio(frame.payload)
            elif not rt.eng.media.append_video(session_id, frame.payload):
                log.warning("video size cap reached session=%s", session_id)
            received += 1
            if received % ACK_EVERY == 0:
                await rt.send("ack", ack_seq=highest, missing=missing)  # 봉투 seq 와 구분 (TRD §7.7)
    except Exception as e:  # noqa: BLE001
        log.info("media channel closed: %s", type(e).__name__)
