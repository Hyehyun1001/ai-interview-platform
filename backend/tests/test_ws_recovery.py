"""재접속 · 장애 복구 (NFR-Q2, TRD §4.5): 끊겨도 저장된 답변이 유실되지 않고 현재 상태가 재전송된다."""
from __future__ import annotations

from datetime import datetime, timezone

from starlette.testclient import TestClient

from app.main import create_app
from app.models import InterviewTurn
from app.models.enums import AnswerEndReason, SessionState, TurnKind
from tests.fakes import FakeSTT
from tests.test_ws_flow import answer, sender_for
from tests.ws_env import Ctl, pcm, start_answer


def paused(env) -> bool:  # noqa: ANN001
    return env.session_row().state == SessionState.PAUSED


def test_disconnect_while_question_is_playing_pauses_and_reconnect_replays_same_question(make_env):
    env = make_env()
    with env.control() as ws:
        q1 = Ctl(ws).until("question")
    env.wait_for(lambda: paused(env), what="paused")  # 끊기면 세션은 paused 로 유지 (TRD §4.5)
    with env.control() as ws2:
        c2 = Ctl(ws2)
        c2.until("session_ready")
        again = c2.until("question")
        assert again["turn_id"] == q1["turn_id"] and again["text"] == q1["text"]  # 새 질문을 만들지 않고 같은 턴을 처음부터 재개
        c2.until("tts_chunk", turn_id=q1["turn_id"], idx=0)  # 질문 재낭독
        assert env.session_row().state == SessionState.IN_PROGRESS
    assert len(env.turns()) == 1


def test_reconnect_during_answer_continues_same_recording_with_remaining_time(make_env):
    env = make_env(slots=1)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        start_answer(env, ctl, q1["turn_id"])
        sender_for(mws).audio(500)
        sender_for(mws).audio(500)
        ctl.drain()
    env.wait_for(lambda: paused(env), what="paused")
    tok2 = env.tokens()
    with env.control(tok2["control_token"]) as ws2, env.media(tok2["media_token"]) as mws2:
        c2 = Ctl(ws2)
        c2.until("session_ready")
        q = c2.until("question")
        assert q["turn_id"] == q1["turn_id"] and 0 < q["time_limit_sec"] <= 60  # 서버 타이머 기준 남은 시간
        assert q["resumed"] is True and q1["resumed"] is False  # 클라이언트가 "새 질문"과 "답변 재개"를 추측 없이 구분한다
        c2.drain()
        assert not c2.of("tts_chunk") and not c2.of("countdown")  # 답변 창은 닫히지 않았으므로 낭독/카운트다운 없이 이어서 진행
        s2 = sender_for(mws2)
        s2.audio(500)
        s2.audio(500)
        c2.send(type="answer_end", turn_id=q1["turn_id"], reason="user")
        c2.until("stt_final")
        c2.until("session_finished")
    pcm_files = list((env.media_root / str(env.session_id)).glob("*.pcm"))
    assert len(pcm_files) == 1 and pcm_files[0].stat().st_size == 4 * len(pcm(500))  # 끊기기 전/후 오디오가 한 파일에 이어진다


def test_answer_is_finalized_from_saved_audio_when_client_does_not_return_in_time(make_env):
    env = make_env(slots=2, tuning={"reconnect_grace_s": 0.1})
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        start_answer(env, ctl, q1["turn_id"])
        s = sender_for(mws)
        for _ in range(6):
            s.audio(500)
        ctl.drain()
    env.wait_for(lambda: len(env.turns()) == 2, what="next question created while disconnected")
    t1, t2 = env.turns()
    assert t1.answer_end_reason == AnswerEndReason.TIMEOUT and t1.answer_text == "Redis로 캐시를 붙여서 속도를 올렸어요"  # 저장된 PCM 으로 STT 재처리
    assert t1.answer_duration_ms == 3000 and t2.kind == TurnKind.MAIN
    with env.control() as ws2:
        c2 = Ctl(ws2)
        c2.until("session_ready")
        q = c2.until("question")
        assert q["turn_id"] == str(t2.id) and q["progress"]["main"] == 2  # 이미 끝난 1번이 아니라 다음 질문부터


def test_disconnect_during_stt_does_not_lose_the_answer(make_env):
    env = make_env(slots=2, stt=FakeSTT(delay=0.3))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"], ms=2000)
        ctl.until("thinking", stage="stt")
    env.wait_for(lambda: len(env.turns()) == 2, what="pipeline finished while disconnected")
    assert env.turns()[0].answer_text and env.turns()[0].answer_end_reason == AnswerEndReason.USER
    with env.control() as ws2:
        c2 = Ctl(ws2)
        c2.until("session_ready")
        assert c2.until("question")["turn_id"] == str(env.turns()[1].id)


def test_expired_pause_aborts_session_and_blocks_reconnect(make_env):
    env = make_env(tuning={"pause_ttl_s": 0.1})
    with env.control() as ws:
        Ctl(ws).until("question")
    env.wait_for(lambda: env.session_row().state == SessionState.ABORTED, what="aborted")
    assert env.session_row().ended_at is not None and env.app.state.session_manager.get(env.session_id) is None
    r = env.client.post(f"/api/v1/sessions/{env.session_id}/ws-token")
    assert r.status_code == 409 and r.json()["error"]["details"]["state"] == "aborted"


def test_reconnect_before_pause_expiry_cancels_the_expiry(make_env):
    env = make_env(tuning={"pause_ttl_s": 0.4})
    with env.control() as ws:
        Ctl(ws).until("question")
    env.wait_for(lambda: paused(env), what="paused")
    with env.control() as ws2:
        c2 = Ctl(ws2)
        c2.until("question")
        import time

        time.sleep(0.6)  # 원래 만료 시각을 지나도 재접속했으므로 중단되지 않는다
        c2.drain()  # 연결이 살아 있어 ping/pong 이 오간다
        assert env.session_row().state == SessionState.IN_PROGRESS
        assert env.app.state.session_manager.get(env.session_id) is not None


def test_server_restart_restores_unanswered_question_from_database(make_env):
    env = make_env()
    with env.control() as ws:
        q1 = Ctl(ws).until("question")
    env.client.__exit__(None, None, None)  # 서버 종료 (메모리의 런타임 소실)
    env.app = create_app(env.settings, env.engines)
    env.client = TestClient(env.app)
    env.client.__enter__()  # 같은 DB 로 새 프로세스 기동
    env.login()
    with env.control() as ws2:
        c2 = Ctl(ws2)
        c2.until("session_ready")
        q = c2.until("question")
        assert q["turn_id"] == q1["turn_id"] and q["text"] == q1["text"]  # DB 가 단일 진실 원천 (TRD §4.5)
    assert len(env.turns()) == 1


def test_server_restart_after_answer_saved_but_before_next_question_continues_without_reasking(make_env):
    env = make_env(slots=2)

    async def insert_answered_turn(s):  # noqa: ANN001, ANN202
        import uuid

        now = datetime.now(timezone.utc)
        s.add(InterviewTurn(id=uuid.uuid4(), session_id=env.session_id, turn_no=1, kind=TurnKind.MAIN, main_index=0,
                            question_text="1번째 질문입니다. 설명해 주세요.", asked_at=now, answer_started_at=now, answer_ended_at=now,
                            answer_duration_ms=3000, answer_text="서버가 죽기 전에 저장된 답변", answer_end_reason=AnswerEndReason.USER))
        await s.commit()

    env.db(insert_answered_turn)
    with env.control() as ws:
        ctl = Ctl(ws)
        ctl.until("session_ready")
        q = ctl.until("question")
        assert q["turn_no"] == 2 and q["progress"] == {"main": 2, "total": 2}  # 1번을 다시 묻지 않고 이어서 진행
    assert env.brain.followup_ctxs[0].answer == "서버가 죽기 전에 저장된 답변"  # 저장된 답변으로 꼬리질문 판단을 이어감
    assert env.brain.main_calls == [1]


def test_code_followup_text_answer_is_persisted(make_env):
    """코딩테스트 연동(v2)에서 만들어질 code_followup 턴의 텍스트 답변 처리 경로 (TTS·카운트다운·STT 없음)."""
    env = make_env(slots=1, coding=True)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        assert ctl.until("session_finished")["next"] == "coding"
        rt = env.app.state.session_manager.get(env.session_id)

        async def begin():  # noqa: ANN202
            return await rt._begin_question(kind=TurnKind.CODE_FOLLOWUP, text="이 코드의 시간복잡도는 얼마인가요?", text_mode=True)

        turn = env.client.portal.call(begin)
        cq = ctl.until("question", kind="code_followup")
        assert cq["tts"] is False and cq["turn_id"] == str(turn.turn_id)
        ctl.send(type="text_answer", turn_id=cq["turn_id"], text="O(n log n) 입니다.")
        ctl.until("session_finished")
    row = [t for t in env.turns() if t.kind == TurnKind.CODE_FOLLOWUP][0]
    assert row.answer_text == "O(n log n) 입니다." and row.answer_audio_path is None and row.answer_end_reason == AnswerEndReason.USER
    assert not [m for m in ctl.of("tts_chunk") if m["turn_id"] == cq["turn_id"]]  # 코드 질문은 음성 합성을 하지 않는다
    assert not [m for m in ctl.of("countdown") if m["turn_id"] == cq["turn_id"]]  # 카운트다운도 없다
