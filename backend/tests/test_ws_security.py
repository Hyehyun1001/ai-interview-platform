"""WebSocket 인증·권한·동시 세션 한도·프로토콜 오남용·미디어 채널 (TRD §4.1, §7.4, §8.3, §11 #14)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update
from starlette.testclient import TestClient, WebSocketDisconnect

from app.core.ws_tokens import issue_ws_token
from app.interview import protocol
from app.models import User
from app.models.enums import SessionState
from tests.conftest import TEST_JWT_SECRET
from tests.test_ws_flow import answer, sender_for
from tests.ws_env import Ctl, close_code, pcm, start_answer, wait_answering

SECRET = TEST_JWT_SECRET


def forged(env, *, user=None, session=None, channel="control", ttl=60) -> str:
    return issue_ws_token(SECRET, user or env.user_id, session or env.session_id, channel, ttl)


def error_and_close(ctx) -> tuple[dict, int]:
    """연결 직후 서버가 보내는 에러 메시지와 close code."""
    with ctx as ws:
        err = ws.receive_json()
        try:
            while True:
                ws.receive_json()
        except WebSocketDisconnect as e:
            return err, e.code


# ── REST: ws-token / state ───────────────────────────────────────────────────
def test_ws_token_endpoint_returns_two_short_lived_channel_tokens(make_env):
    env = make_env()
    r = env.client.post(f"/api/v1/sessions/{env.session_id}/ws-token")
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in"] == 60 and body["control_token"] != body["media_token"]
    with env.control(body["control_token"]), env.media(body["media_token"]):
        pass


def test_ws_token_requires_login_applicant_role_and_ownership(make_env):
    env = make_env(extra_sessions=1)
    url = f"/api/v1/sessions/{env.session_id}/ws-token"
    anon = TestClient(env.app)
    assert anon.post(url).status_code == 401
    assert env.client.post(f"/api/v1/sessions/{env.extra['extra_sessions'][0]}/ws-token").status_code == 404  # 남의 세션은 존재도 숨긴다
    assert env.client.post(f"/api/v1/sessions/{uuid.uuid4()}/ws-token").status_code == 404
    env.client.post("/api/v1/auth/login", json={"email": "hr@corp.local", "password": "Passw0rd!", "role": "recruiter"})
    assert env.client.post(url).status_code == 403  # 담당자는 지원자 면접 세션에 접속할 수 없다


@pytest.mark.parametrize("state", [SessionState.CREATED, SessionState.FINISHED, SessionState.ABORTED])
def test_ws_token_rejected_for_inactive_session_states(make_env, state):
    env = make_env(state=state)
    r = env.client.post(f"/api/v1/sessions/{env.session_id}/ws-token")
    assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_NOT_ACTIVE" and r.json()["error"]["details"]["state"] == state.value


def test_session_state_endpoint_before_and_after_first_question(make_env):
    env = make_env(slots=2)
    s = env.state_json()
    assert (s["state"], s["current_turn_no"], s["total_main"], s["current_turn"], s["degraded_mode"]) == ("ready", 0, 2, None, False)
    with env.control() as ws:
        ctl = Ctl(ws)
        q = ctl.until("question")
        s = env.state_json()
        assert s["state"] == "in_progress" and s["current_turn"]["turn_id"] == q["turn_id"]
        assert s["current_turn"]["kind"] == "main" and s["current_turn"]["remaining_sec"] is None  # 아직 답변 전
        ctl.send(type="tts_done", turn_id=q["turn_id"])
        ctl.until("countdown")
        ctl.send(type="answer_start", turn_id=q["turn_id"])
        wait_answering(env)
        assert 0 < env.state_json()["current_turn"]["remaining_sec"] <= 60


def test_state_endpoint_hides_other_users_sessions(make_env):
    env = make_env(extra_sessions=1)
    assert env.client.get(f"/api/v1/sessions/{env.extra['extra_sessions'][0]}/state").status_code == 404
    assert TestClient(env.app).get(f"/api/v1/sessions/{env.session_id}/state").status_code == 401


# ── 핸드셰이크 인증 ──────────────────────────────────────────────────────────
def test_connect_without_or_with_garbage_token_is_closed_4401(make_env):
    env = make_env()
    err, code = error_and_close(env.client.websocket_connect(f"/ws/sessions/{env.session_id}/control"))
    assert code == 4401 and err["type"] == "error" and err["code"] == "UNAUTHORIZED" and err["recoverable"] is False
    assert close_code(env.control(token="garbage")) == 4401
    assert close_code(env.control(token=forged(env, ttl=-1))) == 4401  # 만료


def test_token_is_single_use(make_env):
    env = make_env()
    token = env.tokens()["control_token"]
    with env.control(token) as ws:
        Ctl(ws).until("session_ready")
    assert close_code(env.control(token)) == 4401  # 재사용 불가 (TRD §4.1 1회용)


def test_token_is_bound_to_channel_and_session(make_env):
    env = make_env(extra_sessions=1)
    t = env.tokens()
    assert close_code(env.control(t["media_token"])) == 4401  # media 토큰으로 control 접속 불가
    assert close_code(env.media(t["control_token"])) == 4401
    assert close_code(env.control(env.tokens()["control_token"], session_id=env.extra["extra_sessions"][0])) == 4401  # 다른 세션 경로


def test_forged_token_for_foreign_or_missing_or_inactive_resources(make_env):
    env = make_env(extra_sessions=1)
    other_sid = env.extra["extra_sessions"][0]
    # 지원자 A 의 유효한 토큰이라도 B 의 세션이면 거부 (NFR-S6)
    assert close_code(env.control(forged(env, session=other_sid), session_id=other_sid)) == 4403
    ghost = uuid.uuid4()
    assert close_code(env.control(forged(env, session=ghost), session_id=ghost)) == 4404

    async def deactivate(s):  # noqa: ANN001, ANN202
        await s.execute(update(User).where(User.id == env.user_id).values(is_active=False))
        await s.commit()

    env.db(deactivate)
    assert close_code(env.control(forged(env))) == 4403  # 토큰 발급 후 비활성화된 계정


def test_finished_session_cannot_connect(make_env):
    env = make_env(state=SessionState.FINISHED)
    err, code = error_and_close(env.control(forged(env)))
    assert code == 4409 and err["code"] == "SESSION_NOT_ACTIVE"


# ── 단일 연결 · 동시 세션 한도 ───────────────────────────────────────────────
def test_second_control_connection_is_rejected_and_first_keeps_working(make_env):
    env = make_env()
    with env.control() as first:
        ctl = Ctl(first)
        ctl.until("question")
        err, code = error_and_close(env.control())
        assert code == 4409 and err["code"] == "ALREADY_CONNECTED" and "다른 창" in err["message"]
        assert ctl.drain()  # 기존 연결은 영향 없음


def test_media_requires_control_channel_first(make_env):
    env = make_env()
    err, code = error_and_close(env.media())
    assert code == 4409 and err["code"] == "CONTROL_REQUIRED"


def test_concurrent_session_limit_then_slot_released_after_pause_expiry(make_env):
    env = make_env(extra_sessions=1, tuning={"pause_ttl_s": 0.2})
    other_sid = env.extra["extra_sessions"][0]
    with env.control() as a:
        Ctl(a).until("question")
        env.login(email="other@corp.local")
        t = env.tokens(other_sid)
        err, code = error_and_close(env.control(t["control_token"], session_id=other_sid))
        assert code == 4409 and err["code"] == "SESSION_SLOT_UNAVAILABLE"  # MAX_CONCURRENT_SESSIONS=1 (클라이언트가 재시도)
    # A 가 끊긴 뒤에도 paused 동안은 슬롯을 점유한다
    assert env.app.state.session_manager.get(env.session_id) is not None
    env.wait_for(lambda: env.app.state.session_manager.get(env.session_id) is None, what="pause expiry")
    assert env.session_row().state == SessionState.ABORTED  # 만료 시 aborted
    t2 = env.tokens(other_sid)
    with env.control(t2["control_token"], session_id=other_sid) as b:
        Ctl(b).until("session_ready")


# ── 프로토콜 오남용: 연결은 유지하고 오류만 알린다 ───────────────────────────
def test_malformed_messages_get_recoverable_errors_and_connection_survives(make_env):
    env = make_env()
    with env.control() as ws:
        ctl = Ctl(ws)
        q = ctl.until("question")
        for raw in ("not json", "{}", '{"type": "mystery"}', '{"type": "tts_done"}', '{"type": "ping", "extra": 1}', '["array"]', "x" * 70_000):
            ws.send_text(raw)
            err = ctl.until("error")
            assert err["code"] == "BAD_MESSAGE" and err["recoverable"] is True
            assert "x" * 50 not in err["message"] and "not json" not in err["message"]  # 입력을 되돌려주지 않는다
        ws.send_bytes(b"\x01\x02")  # 제어 채널의 바이너리 프레임
        assert ctl.until("error")["code"] == "BAD_MESSAGE"
        ctl.send(type="tts_done", turn_id=str(uuid.uuid4()))
        assert ctl.until("error")["code"] == "BAD_TURN"
        ctl.send(type="answer_start", turn_id=q["turn_id"])  # 질문 낭독 중(ASKING)에는 시작할 수 없다
        assert ctl.until("error")["code"] == "BAD_STATE"
        ctl.send(type="answer_end", turn_id=q["turn_id"], reason="user")  # 답변 중이 아니면 조용히 무시 (멱등)
        assert ctl.drain()


def test_duplicate_and_out_of_order_client_seq_are_ignored(make_env):
    env = make_env()
    with env.control() as ws:
        ctl = Ctl(ws)
        ctl.until("question")
        for seq in (5, 5, 3, 6):
            ctl.send(type="ping", seq=seq)
        ctl.send(type="tts_done", turn_id=str(uuid.uuid4()))  # 앞선 메시지가 모두 처리된 뒤에 오는 표식(BAD_TURN)
        ctl.until("error", code="BAD_TURN")
        assert len(ctl.of("pong")) == 2  # seq 5, 6 만 처리 — 중복 5 와 역순 3 은 무시


def test_ping_pong_and_server_keepalive_ping(make_env):
    env = make_env(tuning={"ping_interval_s": 0.05})
    with env.control() as ws:
        ctl = Ctl(ws)
        ctl.until("ping")  # 서버가 주기적으로 ping 을 보낸다 (TRD §7.7)
        ctl.send(type="pong")
        ctl.send(type="ping")
        ctl.until("pong")


def test_idle_connection_is_closed_with_4408(make_env):
    env = make_env(tuning={"ping_interval_s": 0.05})
    assert close_code(env.control()) == 4408  # 3 주기(≈0.15s) 동안 클라이언트 메시지가 없으면 종료


# ── 미디어 채널 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [b"\x01\x00", b"\x07\x00\x00\x00\x00xx", protocol.build_frame(protocol.AUDIO, 0, b"abc")])
def test_malformed_media_frames_close_4400(make_env, raw):
    env = make_env()
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws:
        Ctl(ws).until("question")
        with env.media(tok["media_token"]) as mws:
            mws.send_bytes(raw)
            with pytest.raises(WebSocketDisconnect) as e:
                mws.receive_json()
            assert e.value.code == 4400


def test_text_frame_on_media_channel_closes_4400(make_env):
    env = make_env()
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws:
        Ctl(ws).until("question")
        with env.media(tok["media_token"]) as mws:
            mws.send_text("hello")
            with pytest.raises(WebSocketDisconnect) as e:
                mws.receive_json()
            assert e.value.code == 4400


def test_audio_outside_answer_window_is_dropped_but_video_is_stored(make_env):
    env = make_env()
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        ctl.until("question")
        s = sender_for(mws)
        s.audio(500)  # 질문 낭독 중 마이크 유입 → 버린다 (TRD §4.2)
        s.video(b"webm-1")
        s.video(b"webm-2")
        ctl.drain()
        env.wait_for(lambda: (env.media_root / str(env.session_id) / "video.webm").exists(), what="video file")
        rt = env.app.state.session_manager.get(env.session_id)
        assert rt.media_frames_dropped == 1
        assert (env.media_root / str(env.session_id) / "video.webm").read_bytes() == b"webm-1webm-2"
        assert not list((env.media_root / str(env.session_id)).glob("*.pcm"))


def test_duplicate_frames_are_skipped_and_gaps_are_reported_in_ack(make_env):
    env = make_env()
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q = ctl.until("question")
        start_answer(env, ctl, q["turn_id"])
        for seq in (0, 1, 1, 0, 2, 3, 10):  # 재전송된 중복(1, 0)은 무시, 4~9 는 손실
            mws.send_bytes(protocol.build_frame(protocol.AUDIO, seq, pcm(500)))
        ack = ctl.until("ack")
        assert ack["ack_seq"] == 10 and ack["missing"] == 6  # 5번째로 수락된 프레임에서 ack: 손실 6청크를 알린다
        ctl.send(type="answer_end", turn_id=q["turn_id"], reason="user")
        ctl.until("stt_final")
    pcm_files = list((env.media_root / str(env.session_id)).glob("*.pcm"))
    assert len(pcm_files) == 1 and pcm_files[0].stat().st_size == 5 * len(pcm(500))  # 수락된 5개만 디스크에 있다


def test_ack_envelope_seq_and_media_ack_seq_do_not_collide(make_env):
    env = make_env()
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q = ctl.until("question")
        start_answer(env, ctl, q["turn_id"])
        s = sender_for(mws)
        for _ in range(5):
            s.audio(500)
        ack = ctl.until("ack")
        assert ack["type"] == "ack" and ack["seq"] > 0 and ack["ack_seq"] == 4  # 봉투 seq(제어 메시지 번호) 와 ack_seq(미디어) 구분


def test_audio_arriving_after_the_answer_ended_is_dropped_without_breaking_the_stream(make_env):
    env = make_env(slots=2)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        s = answer(env, ctl, mws, q1["turn_id"], ms=1500)
        ctl.until("stt_final")  # 답변은 이미 종료·확정되었다
        rt = env.app.state.session_manager.get(env.session_id)
        before, dropped = (env.media_root / str(env.session_id) / f"{q1['turn_id']}.pcm").stat().st_size, rt.media_frames_dropped
        s.audio(500)  # 네트워크 지연으로 뒤늦게 도착한 청크
        s.audio(500)
        q2 = ctl.until("question")
        ctl.drain()
        assert rt.media_frames_dropped == dropped + 2  # 닫힌 파일에 쓰지 않고 버린다
        assert (env.media_root / str(env.session_id) / f"{q1['turn_id']}.pcm").stat().st_size == before  # 확정된 답변 오디오는 변하지 않는다
        # 미디어 연결은 계속 살아 있어 다음 질문의 답변을 정상 수신한다
        answer(env, ctl, mws, q2["turn_id"], ms=1500)
        assert ctl.until("stt_final", turn_id=q2["turn_id"])["text"]
