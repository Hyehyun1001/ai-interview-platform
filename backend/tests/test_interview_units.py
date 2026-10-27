"""WS 파이프라인 구성요소 단위 테스트: 프레임 파서 · 토큰 · VAD · 미디어 저장 · 증분 STT · 메시지 스키마 (TRD §4.1~4.2, §7.7)."""
from __future__ import annotations

import asyncio
import os
import stat
import uuid
from datetime import timedelta

import numpy as np
import pytest

from app.ai.stt.base import SttResult, pcm_duration_ms
from app.core.errors import ApiError
from app.core.security import create_token_with_claims
from app.core.ws_tokens import WsTokenRegistry, issue_ws_token, verify_ws_token
from app.interview import protocol
from app.interview.incremental_stt import IncrementalStt
from app.interview.media_store import MAX_VIDEO_BYTES, MediaStore
from app.interview.vad import FRAME_BYTES, EnergyVad
from app.schemas.ws import CLIENT_ADAPTER, MAX_TEXT_ANSWER_CHARS, SERVER_TYPES, server_message
from tests.conftest import TEST_JWT_SECRET
from tests.fakes import FakeSTT

S = TEST_JWT_SECRET


def pcm(ms: int, amp: int = 0) -> bytes:
    """16kHz mono PCM16. amp>0 이면 440Hz 사인파(발화), 0 이면 무음."""
    n = 16 * ms
    if amp == 0:
        return bytes(n * 2)
    t = np.arange(n) / 16000
    return (np.sin(2 * np.pi * 440 * t) * amp).astype(np.int16).tobytes()


# ── 미디어 프레임 ────────────────────────────────────────────────────────────
def test_frame_roundtrip_and_header_layout():
    raw = protocol.build_frame(protocol.AUDIO, 258, b"\x01\x00\x02\x00")
    assert raw[:5] == b"\x01\x00\x00\x01\x02"  # [type][seq uint32 BE]
    f = protocol.parse_frame(raw)
    assert (f.type, f.seq, f.payload) == (protocol.AUDIO, 258, b"\x01\x00\x02\x00")
    assert protocol.parse_frame(protocol.build_frame(protocol.VIDEO, 2**32 - 1, b"webm")).seq == 2**32 - 1


@pytest.mark.parametrize("raw", [b"", b"\x01\x00\x00", b"\x09\x00\x00\x00\x01xx", protocol.build_frame(protocol.AUDIO, 1, b"abc"),
                                 protocol.build_frame(protocol.AUDIO, 1, bytes(protocol.MAX_AUDIO_PAYLOAD + 2)),
                                 protocol.build_frame(protocol.VIDEO, 1, bytes(protocol.MAX_VIDEO_PAYLOAD + 1))])
def test_frame_rejects_malformed(raw):
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_frame(raw)


# ── WS 토큰 (60초, 1회용, 채널·세션 결속) ────────────────────────────────────
def test_ws_token_valid_once_then_replay_rejected():
    uid, sid, reg = uuid.uuid4(), uuid.uuid4(), WsTokenRegistry()
    token = issue_ws_token(S, uid, sid, "control", 60)
    assert verify_ws_token(S, token, session_id=sid, channel="control", registry=reg) == uid
    with pytest.raises(ApiError):
        verify_ws_token(S, token, session_id=sid, channel="control", registry=reg)


def test_ws_token_bound_to_channel_session_and_type():
    uid, sid = uuid.uuid4(), uuid.uuid4()
    token = issue_ws_token(S, uid, sid, "control", 60)
    for kwargs in ({"session_id": sid, "channel": "media"}, {"session_id": uuid.uuid4(), "channel": "control"}):
        with pytest.raises(ApiError):
            verify_ws_token(S, token, registry=WsTokenRegistry(), **kwargs)
    from app.core.security import create_token

    access = create_token(S, uid, "applicant", "access", timedelta(minutes=5))  # access 토큰으로는 WS 접속 불가
    with pytest.raises(ApiError):
        verify_ws_token(S, access, session_id=sid, channel="control", registry=WsTokenRegistry())
    with pytest.raises(ApiError):
        verify_ws_token(S, issue_ws_token(S, uid, sid, "control", -1), session_id=sid, channel="control", registry=WsTokenRegistry())
    with pytest.raises(ApiError):
        verify_ws_token(S, "garbage", session_id=sid, channel="control", registry=WsTokenRegistry())


def test_ws_registry_prunes_expired_entries():
    now = [1000.0]
    reg = WsTokenRegistry(clock=lambda: now[0])
    assert reg.consume("a", 1060.0) and not reg.consume("a", 1060.0)
    now[0] = 1061.0  # 만료된 jti 는 정리되어 메모리가 무한히 늘지 않는다
    assert reg.consume("b", 1121.0) and "a" not in reg._used


def test_ws_token_cannot_be_forged_without_secret():
    uid, sid = uuid.uuid4(), uuid.uuid4()
    forged = create_token_with_claims("x" * 40, uid, "ws", timedelta(seconds=60), {"sid": str(sid), "ch": "control"})
    with pytest.raises(ApiError):
        verify_ws_token(S, forged, session_id=sid, channel="control", registry=WsTokenRegistry())


# ── 클라이언트 메시지 스키마 ─────────────────────────────────────────────────
TID = str(uuid.uuid4())


@pytest.mark.parametrize("payload", [
    {"type": "tts_done", "turn_id": TID}, {"type": "answer_start", "turn_id": TID, "seq": 3},
    {"type": "answer_end", "turn_id": TID, "reason": "user"}, {"type": "answer_end", "turn_id": TID, "reason": "timeout"},
    {"type": "text_answer", "turn_id": TID, "text": "답"}, {"type": "resume", "last_turn_id": TID}, {"type": "resume"},
    {"type": "gaze_event", "turn_id": TID, "kind": "gaze_away", "start_ms": 0, "end_ms": 10, "yaw": 31.2, "confidence": 0.88},
    {"type": "ping"}, {"type": "pong"}])
def test_client_messages_accept_valid(payload):
    assert CLIENT_ADAPTER.validate_python(payload).type == payload["type"]


@pytest.mark.parametrize("payload", [
    {"type": "unknown"}, {"type": "tts_done"}, {"type": "tts_done", "turn_id": "not-uuid"},
    {"type": "answer_end", "turn_id": TID, "reason": "silence"},  # silence 는 서버만 판정한다
    {"type": "answer_end", "turn_id": TID, "reason": "user", "extra": 1},  # 알 수 없는 필드 거부
    {"type": "text_answer", "turn_id": TID, "text": "x" * (MAX_TEXT_ANSWER_CHARS + 1)},
    {"type": "gaze_event", "turn_id": TID, "kind": "wink", "start_ms": 0, "end_ms": 1},
    {"type": "gaze_event", "turn_id": TID, "kind": "gaze_away", "start_ms": -1, "end_ms": 1},
    {"type": "gaze_event", "turn_id": TID, "kind": "gaze_away", "start_ms": 0, "end_ms": 1, "confidence": 1.5},
    {"type": "ping", "seq": -1}, {}])
def test_client_messages_reject_invalid(payload):
    with pytest.raises(Exception):
        CLIENT_ADAPTER.validate_python(payload)


def test_server_message_envelope_and_known_types_only():
    m = server_message("question", 7, turn_id="t")
    assert m["type"] == "question" and m["seq"] == 7 and m["ts"].endswith("+00:00") and m["turn_id"] == "t"
    assert {"session_ready", "question", "tts_chunk", "countdown", "thinking", "stt_final", "gaze_warning", "degraded", "error",
            "session_finished", "ack"} <= SERVER_TYPES
    with pytest.raises(ValueError):
        server_message("nope", 1)
    # 페이로드가 봉투 키를 덮어쓰면 즉시 오류 (ack 의 미디어 seq 는 ack_seq 로 구분): seq 는 파이썬이 TypeError, type/ts 는 ValueError
    with pytest.raises(TypeError):
        server_message("ack", 1, seq=5)
    for key in ("type", "ts"):
        with pytest.raises(ValueError):
            server_message("ack", 1, **{key: "x"})


# ── VAD ──────────────────────────────────────────────────────────────────────
def test_vad_tracks_speech_and_trailing_silence():
    v = EnergyVad(400)
    v.feed(pcm(500))  # 앞쪽 무음은 침묵 시간으로 세지 않는다 (발화 전)
    assert not v.has_speech and v.silence_run_ms == 0
    v.feed(pcm(600, 3000))
    assert v.has_speech and v.speech_ms == 600 and v.silence_run_ms == 0
    v.feed(pcm(1500))
    assert v.silence_run_ms == 1500
    v.feed(pcm(100, 3000))
    assert v.silence_run_ms == 0 and v.speech_ms == 700  # 발화가 다시 시작되면 침묵 누적이 초기화된다


def test_vad_handles_chunks_that_are_not_frame_aligned():
    v = EnergyVad(400)
    audio = pcm(1000, 3000)
    for i in range(0, len(audio), 777):  # 임의 크기로 쪼개 도착해도 결과는 같아야 한다
        v.feed(audio[i:i + 777 - (777 % 2)] if i + 777 <= len(audio) else audio[i:])
    assert abs(v.speech_ms - 1000) <= 20 and len(v._rest) < FRAME_BYTES


def test_vad_threshold_ignores_low_noise():
    v = EnergyVad(400)
    v.feed(pcm(500, 100))  # 배경 소음 수준
    assert not v.has_speech


# ── 미디어 저장 ──────────────────────────────────────────────────────────────
def test_answer_recording_appends_immediately_and_survives_reopen(tmp_path):
    store, sid, tid = MediaStore(tmp_path), uuid.uuid4(), uuid.uuid4()
    rec = store.open_answer(sid, tid)
    rec.append(pcm(500, 1000))
    assert store.answer_path(sid, tid).stat().st_size == len(pcm(500, 1000))  # close 전에도 디스크에 반영 (NFR-Q2)
    assert rec.duration_ms == 500
    rec.close()
    rec2 = store.open_answer(sid, tid)  # 재접속/재개: 이어 쓰기
    rec2.append(pcm(250, 1000))
    assert rec2.duration_ms == 750 and len(rec2.read_all()) == 24000
    rec2.close()


def test_media_files_are_private_and_named_by_uuid_only(tmp_path):
    store, sid, tid = MediaStore(tmp_path / "media"), uuid.uuid4(), uuid.uuid4()
    rec = store.open_answer(sid, tid)
    rec.close()
    store.append_video(sid, b"webm-chunk")
    d = tmp_path / "media" / str(sid)
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    for f in d.iterdir():
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert sorted(f.name for f in d.iterdir()) == sorted([f"{tid}.pcm", "video.webm"])  # 성명·원본 파일명 미노출


def test_video_append_and_size_cap(tmp_path, monkeypatch):
    store, sid = MediaStore(tmp_path), uuid.uuid4()
    assert store.append_video(sid, b"abc") and store.append_video(sid, b"def")
    assert (tmp_path / str(sid) / "video.webm").read_bytes() == b"abcdef"
    monkeypatch.setattr("app.interview.media_store.MAX_VIDEO_BYTES", 8)
    assert not store.append_video(sid, b"x" * 5) and (tmp_path / str(sid) / "video.webm").stat().st_size == 6
    assert MAX_VIDEO_BYTES == 1024 ** 3


def test_pcm_duration_ms():
    assert pcm_duration_ms(32000) == 1000 and pcm_duration_ms(16000) == 500 and pcm_duration_ms(0) == 0


# ── 증분 STT (TRD §2.4 필수 지연 최적화) ─────────────────────────────────────
def make_inc(texts=None, **kw):
    stt = FakeSTT(texts or ["첫째", "둘째", "셋째", "넷째"])
    return stt, IncrementalStt(stt, min_chunk_ms=1000, max_chunk_ms=4000, boundary_silence_ms=200, **kw)


async def test_chunk_is_dispatched_at_silence_boundary_after_min_length():
    stt, inc = make_inc()
    vad = EnergyVad(400)
    for chunk in (pcm(500, 3000), pcm(600, 3000)):
        vad.feed(chunk)
        inc.feed(chunk, vad)
    assert inc.chunks_dispatched == 0  # 1.1초 발화 중에는 경계가 없다
    for _ in range(3):
        silence = pcm(100)
        vad.feed(silence)
        inc.feed(silence, vad)
    assert inc.chunks_dispatched == 1  # 0.2초 침묵 → 확정 구간 디코딩이 백그라운드로 시작됨
    await asyncio.sleep(0)
    assert len(stt.calls) == 1 and stt.calls[0] == len(pcm(1100, 1)) + len(pcm(200))


async def test_short_utterance_does_not_dispatch_at_silence():
    _stt, inc = make_inc()
    vad = EnergyVad(400)
    for chunk in (pcm(300, 3000), pcm(400)):
        vad.feed(chunk)
        inc.feed(chunk, vad)
    assert inc.chunks_dispatched == 0  # 최소 길이 미만이면 침묵이 있어도 확정하지 않는다


async def test_forced_boundary_at_max_chunk_length_without_silence():
    stt, inc = make_inc()
    vad = EnergyVad(400)
    for _ in range(9):
        chunk = pcm(500, 3000)
        vad.feed(chunk)
        inc.feed(chunk, vad)
    assert inc.chunks_dispatched == 1  # 4.5초 연속 발화 → 4초에서 강제 확정
    res = await inc.finish()
    assert len(stt.calls) == 2 and res.text == "첫째 둘째"  # 확정 구간 + 마지막 잔여 구간 1회


async def test_finish_decodes_only_the_remainder_and_keeps_order_even_if_first_chunk_is_slower():
    order = []

    class SlowFirst:
        async def transcribe_pcm(self, pcm_bytes, *, initial_prompt=None):  # noqa: ANN001, ANN201
            n = len(order)
            order.append(n)
            await asyncio.sleep(0.05 if n == 0 else 0)  # 첫 청크가 더 오래 걸려도 결과 순서는 유지되어야 한다
            return SttResult(f"조각{n}", -0.2, 0.01)

    inc = IncrementalStt(SlowFirst(), min_chunk_ms=1000, max_chunk_ms=1000, boundary_silence_ms=200)
    vad = EnergyVad(400)
    for _ in range(3):
        chunk = pcm(500, 3000)
        vad.feed(chunk)
        inc.feed(chunk, vad)
    res = await inc.finish()
    assert res.text == "조각0 조각1" and res.avg_logprob == pytest.approx(-0.2)


async def test_tiny_tail_is_skipped_when_chunks_exist_but_not_when_it_is_the_whole_answer():
    stt, inc = make_inc()
    vad = EnergyVad(400)
    for chunk in (pcm(1200, 3000), pcm(200)):
        vad.feed(chunk)
        inc.feed(chunk, vad)
    tail = pcm(100, 3000)  # 100ms 꼬리 < 300ms
    inc.feed(tail, vad)
    res = await inc.finish()
    assert len(stt.calls) == 1 and res.text == "첫째"  # 꼬리 조각은 디코딩 비용 대비 의미가 없어 건너뛴다
    stt2, inc2 = make_inc(["전체"])
    inc2.feed(pcm(100, 3000), EnergyVad(400))
    assert (await inc2.finish()).text == "전체" and len(stt2.calls) == 1  # 답변 전체가 짧을 땐 그래도 디코딩


async def test_finish_propagates_stt_failure_and_cancel_stops_tasks():
    inc = IncrementalStt(FakeSTT(fail=True), min_chunk_ms=100, max_chunk_ms=100)
    inc.feed(pcm(200, 3000), EnergyVad(400))
    with pytest.raises(RuntimeError):
        await inc.finish()
    stt = FakeSTT(delay=5)
    inc2 = IncrementalStt(stt, min_chunk_ms=100, max_chunk_ms=100)
    inc2.feed(pcm(200, 3000), EnergyVad(400))
    inc2.cancel()
    assert inc2._tasks == []


async def test_low_confidence_flag_follows_stt_quality_signals():
    assert SttResult("").low_confidence and SttResult("  ").low_confidence
    assert SttResult("안녕", -1.5, 0.1).low_confidence and SttResult("안녕", -0.3, 0.9).low_confidence
    assert not SttResult("안녕하세요", -0.3, 0.05).low_confidence and not SttResult("안녕", None, None).low_confidence
