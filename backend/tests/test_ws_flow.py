"""면접 세션 WebSocket 파이프라인 통합 테스트: 질문 → TTS → 카운트다운 → 답변 → STT → 꼬리질문 → 다음 질문 (TRD §4.2, §7.7)."""
from __future__ import annotations



from app.ai.errors import LLMUnavailable
from app.models import GazeEvent
from app.models.enums import AnswerEndReason, FollowupReason, SessionState, TurnKind
from app.schemas.ai import Evidence, FollowupDecision
from tests.fakes import FakeBrain, FakeSTT, FakeTTS
from tests.ws_env import Ctl, MediaSender, _all, close_code, pcm, start_answer, wait_answering  # noqa: F401


def needed(question="Redis 캐시 무효화는 어떻게 처리하셨나요?", reason="ambiguous", evidence=()) -> FollowupDecision:
    return FollowupDecision(needed=True, reason=reason, grounding_keywords=["Redis", "캐시"], question=question, evidence=list(evidence))


def sender_for(media) -> MediaSender:  # noqa: ANN001
    """미디어 연결당 하나의 sender — 프레임 seq 는 연결 내내 이어진다(재시작하면 서버가 중복으로 폐기한다)."""
    if not hasattr(media, "_test_sender"):
        media._test_sender = MediaSender(media)
    return media._test_sender


def answer(env, ctl, med, turn_id, ms=3000, how="user"):  # noqa: ANN001, ANN201
    """한 번 답변: 시작 → 오디오 전송 → 종료."""
    start_answer(env, ctl, turn_id)
    sender = sender_for(med)
    for _ in range(ms // 500):
        sender.audio(500)
    if how == "user":
        ctl.send(type="answer_end", turn_id=turn_id, reason="user")
    return sender


# ── 전체 흐름 ────────────────────────────────────────────────────────────────
def test_full_interview_without_followups(make_env):
    env = make_env(slots=2)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        ready = ctl.until("session_ready")
        assert (ready["total_main"], ready["answer_limit_sec"], ready["max_followups"]) == (2, 60, 2)
        assert ready["coding_test"] == {"enabled": False, "time_limit_sec": None} and ready["seq"] == 1

        q1 = ctl.until("question")
        assert q1["kind"] == "main" and q1["progress"] == {"main": 1, "total": 2} and q1["text"].startswith("1번째") and q1["tts"]
        chunks = [ctl.until("tts_chunk") for _ in range(3)]
        assert [c["idx"] for c in chunks] == [0, 1, 2] and [c["last"] for c in chunks] == [False, False, True]
        assert all(c["format"] == "wav" and c["turn_id"] == q1["turn_id"] for c in chunks)

        answer(env, ctl, mws, q1["turn_id"], ms=3000)
        final = ctl.until("stt_final")
        assert [m["n"] for m in ctl.of("countdown")] == [3, 2, 1]  # 1번 질문의 카운트다운은 3-2-1 전체가 전달된다
        assert final["turn_id"] == q1["turn_id"] and final["text"] == "Redis로 캐시를 붙여서 속도를 올렸어요" and final["low_confidence"] is False
        q2 = ctl.until("question")
        assert q2["progress"] == {"main": 2, "total": 2} and q2["turn_no"] == 2 and q2["kind"] == "main"
        assert env.brain.main_calls == [0, 1] and len(env.brain.followup_ctxs) == 1  # 1번 답변 후 꼬리질문 판단 1회(생략)

        answer(env, ctl, mws, q2["turn_id"], ms=1500)
        ctl.until("stt_final", turn_id=q2["turn_id"])
        fin = ctl.until("session_finished")
        assert fin["next"] == "done" and len(env.brain.followup_ctxs) == 2

        acks = ctl.drain() and ctl.of("ack")
        assert acks and acks[0]["ack_seq"] == 4 and acks[0]["missing"] == 0  # 5번째 청크마다 ack (TRD §7.7)
        seqs = [m["seq"] for m in ctl.log]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # 서버 메시지 seq 는 단조 증가

    turns = env.turns()
    assert [t.turn_no for t in turns] == [1, 2] and all(t.kind == TurnKind.MAIN for t in turns)
    t1 = turns[0]
    assert t1.answer_text == "Redis로 캐시를 붙여서 속도를 올렸어요" and t1.answer_end_reason == AnswerEndReason.USER
    assert t1.answer_duration_ms == 3000 and t1.answer_audio_path == f"{env.session_id}/{t1.id}.pcm"
    assert (env.media_root / t1.answer_audio_path).stat().st_size == len(pcm(3000))  # 받은 오디오가 그대로 디스크에 있다
    sess = env.session_row()
    assert sess.state == SessionState.FINISHED and sess.ended_at is not None and sess.started_at is not None
    assert sess.current_turn_no == 2 and sess.followup_count == 0


def test_followup_is_spoken_as_soon_as_decided_and_keeps_main_progress(make_env):
    ev = [Evidence(source="answer", ref="turn:x", quote="Redis로 캐시")]
    env = make_env(slots=2, brain=FakeBrain(total_main=2, followups=[needed(evidence=ev)]))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        ctl.until("stt_final")
        ctl.until("thinking", stage="analysis")
        fq = ctl.until("question", kind="followup")
        assert fq["text"].startswith("Redis 캐시 무효화") and fq["progress"] == {"main": 1, "total": 2}  # 꼬리질문은 메인 진행률을 올리지 않는다
        assert fq["turn_no"] == 2
        ctl.until("tts_chunk", turn_id=fq["turn_id"])
        assert fq["text"] in env.tts.texts  # 꼬리질문도 음성으로 합성된다
        answer(env, ctl, mws, fq["turn_id"], ms=1500)
        ctl.until("stt_final", turn_id=fq["turn_id"])
        q2 = ctl.until("question", kind="main")
        assert q2["progress"]["main"] == 2 and q2["turn_no"] == 3

    turns = env.turns()
    assert [(t.turn_no, t.kind) for t in turns] == [(1, TurnKind.MAIN), (2, TurnKind.FOLLOWUP), (3, TurnKind.MAIN)]
    f = turns[1]
    assert f.parent_turn_id == turns[0].id and f.followup_reason == FollowupReason.AMBIGUOUS and f.main_index == 0
    assert f.question_evidence and f.question_evidence[0]["quote"] == "Redis로 캐시"  # 스트리밍 경로의 evidence 는 뒤늦게 확정되어 저장
    assert env.session_row().followup_count == 0  # 메인 질문이 바뀌면 횟수 초기화 (VOI-6)


def test_followup_count_is_capped_by_max_followups_and_llm_is_not_called_beyond_it(make_env):
    brain = FakeBrain(total_main=1, max_followups=1, followups=[needed(), needed("Kafka 로 바꾸면 어떻게 되나요?")])
    env = make_env(slots=1, max_followups=1, brain=brain)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        fq = ctl.until("question", kind="followup")
        answer(env, ctl, mws, fq["turn_id"], ms=1500)
        ctl.until("session_finished")  # 최대 1회 → 두 번째 답변 후에는 판단 없이 바로 종료
    assert len(brain.followup_ctxs) == 1 and [t.kind for t in env.turns()] == [TurnKind.MAIN, TurnKind.FOLLOWUP]
    assert brain.followup_ctxs[0].used == 0 and brain.followup_ctxs[0].max_followups == 1


def test_followups_disabled_when_all_triggers_are_off(make_env):
    brain = FakeBrain(total_main=1, followups=[needed()], triggers={"trigger_ambiguous": False, "trigger_contradiction": False,
                                                                    "trigger_stt_unclear": False})
    env = make_env(slots=1, brain=brain)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        ctl.until("session_finished")
    assert brain.followup_ctxs == []  # 규칙상 꼬리질문이 불가하면 LLM 을 호출하지 않는다 (지연 절약)


def test_non_streaming_brain_still_produces_followup_question(make_env):
    env = make_env(slots=1, brain=FakeBrain(total_main=1, followups=[needed()], streaming=False))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        assert ctl.until("question", kind="followup")["text"].startswith("Redis")


def test_stt_unclear_flag_is_passed_to_followup_decision(make_env):
    class Unclear(FakeSTT):
        async def transcribe_pcm(self, pcm_bytes, *, initial_prompt=None):  # noqa: ANN001, ANN201
            from app.ai.stt.base import SttResult

            return SttResult("음 그게 어", -1.8, 0.2)

    env = make_env(slots=1, stt=Unclear())
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        assert ctl.until("stt_final")["low_confidence"] is True
        ctl.until("session_finished")
    assert env.brain.followup_ctxs[0].stt_unclear is True and env.brain.followup_ctxs[0].answer == "음 그게 어"


# ── 종료 방식: 타임아웃 · 침묵 · 짧은 답변 ───────────────────────────────────
def test_server_side_timeout_ends_answer_even_if_client_stays_silent(make_env):
    env = make_env(slots=1, brain=FakeBrain(total_main=1, answer_limit=1), tuning={"timeout_scale": 0.15, "min_answer_ms": 0})
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        assert q1["time_limit_sec"] == 1
        ws.send_json({"type": "tts_done", "turn_id": q1["turn_id"]})
        ctl.until("countdown")
        ws.send_json({"type": "answer_start", "turn_id": q1["turn_id"]})
        ctl.until("thinking", stage="stt")  # answer_end 를 보내지 않아도 서버 타이머가 종료시킨다
        ctl.until("session_finished")
    assert env.turns()[0].answer_end_reason == AnswerEndReason.TIMEOUT


def test_silence_after_speech_ends_answer(make_env):
    env = make_env(slots=1, tuning={"silence_end_ms": 400})
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        ws.send_json({"type": "tts_done", "turn_id": q1["turn_id"]})
        ctl.until("countdown")
        ws.send_json({"type": "answer_start", "turn_id": q1["turn_id"]})
        wait_answering(env)
        s = sender_for(mws)
        s.audio(1500, 3000)  # 발화 1.5초
        s.audio(500, 0)  # 침묵 0.5초 > 0.4초
        ctl.until("thinking", stage="stt")
        ctl.until("session_finished")
    assert env.turns()[0].answer_end_reason == AnswerEndReason.SILENCE


def test_silence_before_any_speech_does_not_end_answer(make_env):
    env = make_env(slots=1, tuning={"silence_end_ms": 200, "timeout_scale": 0.05, "min_answer_ms": 0}, brain=FakeBrain(total_main=1, answer_limit=2))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        ws.send_json({"type": "tts_done", "turn_id": q1["turn_id"]})
        ctl.until("countdown")
        ws.send_json({"type": "answer_start", "turn_id": q1["turn_id"]})
        wait_answering(env)
        sender_for(mws).audio(500, 0)  # 아직 말을 시작하지 않은 무음은 종료 사유가 아니다
        ctl.until("thinking", stage="stt")
    assert env.turns()[0].answer_end_reason == AnswerEndReason.TIMEOUT


def test_too_short_answer_asks_to_repeat_then_gives_up_after_max_reasks(make_env):
    env = make_env(slots=1, tuning={"max_reasks": 1})
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"], ms=500)  # 0.5초 < 1초
        err = ctl.until("error", code="ANSWER_TOO_SHORT")
        assert err["recoverable"] is True and err["message"] == "다시 말씀해 주세요"
        n_countdowns = len(ctl.of("countdown"))
        ctl.until("countdown", n=3)  # 같은 질문의 카운트다운이 다시 시작된다 (질문/TTS 는 재생성하지 않음)
        assert len(ctl.of("question")) == 1 and len(ctl.of("countdown")) > n_countdowns - 1
        ctl.send(type="answer_start", turn_id=q1["turn_id"])
        wait_answering(env)
        sender_for(mws).audio(500)
        ctl.send(type="answer_end", turn_id=q1["turn_id"], reason="user")
        ctl.until("stt_final")  # max_reasks=1 이므로 두 번째 짧은 답변은 그대로 처리한다
        ctl.until("session_finished")
    assert len(env.turns()) == 1
    assert (env.media_root / env.turns()[0].answer_audio_path).stat().st_size == len(pcm(500))  # 첫 시도 오디오는 폐기되고 재시도분만 남는다


def test_answer_start_without_client_message_is_started_by_server(make_env):
    env = make_env(slots=1, tuning={"answer_start_grace_s": 0.1, "timeout_scale": 0.1, "min_answer_ms": 0}, brain=FakeBrain(total_main=1, answer_limit=1))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        ws.send_json({"type": "tts_done", "turn_id": q1["turn_id"]})
        ctl.until("thinking", stage="stt")  # answer_start 없이도 교착되지 않고 서버가 시작→타임아웃까지 진행
    assert env.turns()[0].answer_started_at is not None


def test_client_never_sends_tts_done_server_proceeds_after_timeout(make_env):
    env = make_env(slots=1, tuning={"tts_done_timeout_s": 0.1})
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws:
        ctl = Ctl(ws)
        ctl.until("question")
        ctl.until("countdown", n=3)  # tts_done 이 오지 않아도 카운트다운으로 넘어간다


# ── 장애 복구 ────────────────────────────────────────────────────────────────
def test_tts_failure_keeps_session_alive_with_captions_only(make_env):
    env = make_env(slots=1, tts=FakeTTS(fail=True))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        err = ctl.until("error", code="TTS_FAILED")
        assert err["recoverable"] and not ctl.of("tts_chunk")
        ctl.until("countdown", n=3)  # tts_done 없이도 유예 후 자동 카운트다운 (UI_SPEC §4.6.6)
        ctl.send(type="answer_start", turn_id=q1["turn_id"])
        wait_answering(env)
        s = sender_for(mws)
        for _ in range(3):
            s.audio(500)
        ctl.send(type="answer_end", turn_id=q1["turn_id"], reason="user")
        ctl.until("session_finished")


def test_stt_failure_continues_with_empty_answer(make_env):
    env = make_env(slots=1, stt=FakeSTT(fail=True))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        assert ctl.until("error", code="STT_FAILED")["recoverable"]
        final = ctl.until("stt_final")
        assert final["text"] == "" and final["low_confidence"] is True
        ctl.until("session_finished")  # 세션 중단 없음


def test_llm_unavailable_during_followup_skips_it_and_marks_degraded(make_env):
    env = make_env(slots=2, brain=FakeBrain(total_main=2, followups=[LLMUnavailable("down")]))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        d = ctl.until("degraded")
        assert d["reason"] == "llm_unavailable" and d["message"]
        assert ctl.until("question")["progress"]["main"] == 2  # 꼬리질문만 생략하고 다음 메인 질문으로 진행 (NFR-R5)
    assert env.session_row().degraded_mode is True


def test_coding_enabled_job_hands_over_to_coding_tab(make_env):
    env = make_env(slots=1, coding=True)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        assert ctl.until("session_ready")["coding_test"] == {"enabled": True, "time_limit_sec": 3600}
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        assert ctl.until("session_finished")["next"] == "coding"
    assert env.session_row().state == SessionState.CODING and env.session_row().ended_at is None
    # 코딩 단계 재접속 시 상태를 다시 알려 준다
    with env.control() as ws2:
        c2 = Ctl(ws2)
        c2.until("session_ready")
        assert c2.until("session_finished")["next"] == "coding"


def test_text_answer_rejected_for_voice_question(make_env):
    env = make_env(slots=1)
    with env.control() as ws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        ctl.send(type="text_answer", turn_id=q1["turn_id"], text="코드로 답변")
        assert ctl.until("error", code="BAD_STATE")["recoverable"]


# ── 시선 이벤트 ──────────────────────────────────────────────────────────────
def test_gaze_events_are_stored_and_warnings_capped_at_three(make_env):
    env = make_env(slots=1)
    with env.control() as ws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        start_answer(env, ctl, q1["turn_id"])
        for i in range(4):
            ctl.send(type="gaze_event", turn_id=q1["turn_id"], kind="gaze_away" if i else "face_lost", start_ms=1000 * i,
                     end_ms=1000 * i + 1600, yaw=31.2, pitch=4.1, confidence=0.88)
        ctl.drain()
        warns = ctl.of("gaze_warning")
        assert [w["count"] for w in warns] == [1, 2, 3]  # 세션당 최대 3회 (TRD §4.4)
        assert "얼굴이 보이지 않아요" in warns[0]["message"] and "응시" in warns[1]["message"]
        assert all(w not in warns[0]["message"] for w in ("부정행위", "치팅"))  # 단정적 표현 금지
    rows = env.db(lambda s: _all(s, __import__("sqlalchemy").select(GazeEvent).order_by(GazeEvent.start_ms)))
    assert len(rows) == 4 and rows[0].kind.value == "face_lost" and rows[2].end_ms == 3600  # 경고는 3회여도 이벤트는 전부 저장
    assert rows[1].occurred_at > rows[0].occurred_at and rows[0].yaw == 31.2 and rows[0].turn_id.hex == q1["turn_id"].replace("-", "")


def test_gaze_event_for_unknown_turn_is_rejected(make_env):
    import uuid

    env = make_env(slots=1)
    with env.control() as ws:
        ctl = Ctl(ws)
        ctl.until("question")
        ctl.send(type="gaze_event", turn_id=str(uuid.uuid4()), kind="gaze_away", start_ms=0, end_ms=10)
        assert ctl.until("error", code="BAD_TURN")["recoverable"]


def test_timing_log_has_stage_durations_and_never_contains_user_text(make_env, caplog):
    """지연 병목 확인용 로그: 답변 종료 → 다음 질문 음성의 단계별 시간. 숫자·식별자만 남기고 질문·답변 원문은 남기지 않는다."""
    import logging
    import re

    caplog.set_level(logging.INFO, logger="app.interview.timing")
    env = make_env(slots=2, brain=FakeBrain(total_main=2, followups=[needed("Redis 캐시 무효화는 어떻게 처리하셨나요?")]))
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        q1 = ctl.until("question")
        answer(env, ctl, mws, q1["turn_id"])
        ctl.until("question", kind="followup")
        ctl.until("tts_chunk", last=True)
        env.wait_for(lambda: any("timing session=" in r.getMessage() for r in caplog.records), what="timing log")
    lines = [r.getMessage() for r in caplog.records if r.name == "app.interview.timing"]
    t = next(m for m in lines if m.startswith("timing session="))
    assert "next_kind=followup" in t and re.search(r"decision_needed=True", t)
    for key in ("stt_tail_s", "decide_s", "question_begin_s", "tts_first_chunk_s", "tts_last_chunk_s", "total_s"):
        assert re.search(rf"{key}=\d+\.\d\d", t), key
    blob = "\n".join(lines)
    assert "Redis" not in blob and "번째 질문" not in blob  # 원문 비노출
