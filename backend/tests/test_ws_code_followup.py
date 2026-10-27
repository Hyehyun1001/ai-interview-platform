"""코딩테스트 제출 직후 텍스트(채팅형) 코드 꼬리질문 (TRD §5.6, §7.7, PRD 10장 #1)."""
from __future__ import annotations

import time

import pytest

from app.ai.errors import LLMUnavailable
from app.models.enums import SessionState, TurnKind
from app.schemas.ai import Evidence, FollowupDecision
from tests.fakes import FakeBrain, FakeSandbox
from tests.test_ws_flow import answer
from tests.ws_env import Ctl


def code_q(question: str) -> FollowupDecision:
    return FollowupDecision(needed=True, reason="ambiguous", grounding_keywords=["해시맵", "두 수"], question=question,
                            evidence=[Evidence(source="code", ref="code", quote="seen = {}")])


def to_coding(env, ctl, mws):  # noqa: ANN001, ANN201
    env.app.state.settings.sandbox_enabled = True
    env.app.state.services.sandbox = FakeSandbox()
    answer(env, ctl, mws, ctl.until("question")["turn_id"])
    assert ctl.until("session_finished")["next"] == "coding"


def submit(env, source="ok"):  # noqa: ANN001, ANN201
    r = env.client.post(f"/api/v1/sessions/{env.session_id}/code/submit", json={"language": "python", "source": source})
    assert r.status_code == 202, r.text


def test_code_followup_chat_after_submit_then_back_to_coding(make_env):
    brain = FakeBrain(total_main=1, max_followups=2, coding=True)
    brain.code_followups = [code_q("해시맵을 쓴 이유는 무엇인가요?"), code_q("시간 복잡도는 얼마인가요?")]
    env = make_env(slots=1, coding=True, brain=brain, max_followups=2)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        to_coding(env, ctl, mws)
        submit(env)
        q = ctl.until("question", kind="code_followup")
        assert q["tts"] is False and q["text"] == "해시맵을 쓴 이유는 무엇인가요?" and "tts_chunk" not in ctl.types()[-3:]
        ctl.send(type="text_answer", turn_id=q["turn_id"], text="조회를 O(1) 로 하려고 썼습니다.")
        q2 = ctl.until("question", kind="code_followup")  # 최대 횟수(2) 안에서 다음 꼬리질문
        assert q2["text"] == "시간 복잡도는 얼마인가요?"
        ctl.send(type="text_answer", turn_id=q2["turn_id"], text="O(n) 입니다.")
        assert ctl.until("session_finished")["next"] == "coding"  # 횟수를 채우면 코딩 단계로 돌아간다
    turns = env.turns()
    cf = [t for t in turns if t.kind == TurnKind.CODE_FOLLOWUP]
    assert [t.answer_text for t in cf] == ["조회를 O(1) 로 하려고 썼습니다.", "O(n) 입니다."]
    assert all(t.answer_audio_path is None and t.question_evidence[0]["source"] == "code" for t in cf)  # 음성 없음 · 코드 근거
    assert env.session_row().state == SessionState.CODING
    # 두 번째 질문 생성 시 첫 질문과 답변이 근거에 들어간다
    assert brain.code_histories == [[], [("해시맵을 쓴 이유는 무엇인가요?", "조회를 O(1) 로 하려고 썼습니다.")]]
    assert brain.code_ctxs[0].verdict == "AC"


@pytest.mark.parametrize("item", [FollowupDecision.skip(), LLMUnavailable("down")], ids=["skip", "llm_down"])
def test_no_code_followup_when_model_skips_or_fails(make_env, item):
    if True:
        brain = FakeBrain(total_main=1, max_followups=2, coding=True)
        brain.code_followups = [item]
        env = make_env(slots=1, coding=True, brain=brain, max_followups=2)
        tok = env.tokens()
        with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
            ctl = Ctl(ws)
            to_coding(env, ctl, mws)
            submit(env)
            env.wait_for(lambda b=brain: getattr(b, "code_ctxs", None), what="code followup decision")
            assert not [m for m in ctl.drain() if m["type"] == "question" and m.get("kind") == "code_followup"]
            r = env.client.get(f"/api/v1/sessions/{env.session_id}/code/result")
            assert r.json()["status"] in ("judging", "done")  # 꼬리질문 실패와 무관하게 채점 결과는 유지된다


def test_text_answer_timeout_is_recorded_as_empty_and_wrong_turn_rejected(make_env):
    brain = FakeBrain(total_main=1, max_followups=1, coding=True, answer_limit=1)
    brain.code_followups = [code_q("해시맵을 쓴 이유는 무엇인가요?")]
    env = make_env(slots=1, coding=True, brain=brain, max_followups=1, tuning={"timeout_scale": 0.3})
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        to_coding(env, ctl, mws)
        submit(env)
        q = ctl.until("question", kind="code_followup")
        ctl.send(type="text_answer", turn_id="00000000-0000-0000-0000-000000000000", text="x")
        ctl.until("error", code="BAD_TURN")
        assert ctl.until("session_finished")["next"] == "coding"  # 시간 초과 → 빈 답변으로 처리하고 다음으로
    cf = [t for t in env.turns() if t.kind == TurnKind.CODE_FOLLOWUP]
    assert len(cf) == 1 and cf[0].answer_text == "" and cf[0].answer_end_reason.value == "timeout"
    assert str(cf[0].id) == q["turn_id"]


def test_reconnect_after_unanswered_code_followup_shows_it_again(make_env):
    brain = FakeBrain(total_main=1, max_followups=1, coding=True)
    brain.code_followups = [code_q("해시맵을 쓴 이유는 무엇인가요?")]
    env = make_env(slots=1, coding=True, brain=brain, max_followups=1, tuning={"reconnect_grace_s": 0.1})
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        to_coding(env, ctl, mws)
        submit(env)
        q = ctl.until("question", kind="code_followup")
    time.sleep(0.5)  # 유예 시간(0.1s)이 지나도 텍스트 질문은 무응답으로 처리되지 않는다 (녹음이 없으므로)
    assert [t.answer_text for t in env.turns() if t.kind == TurnKind.CODE_FOLLOWUP] == [None]
    with env.control() as ws2:  # 새로고침/재접속
        c2 = Ctl(ws2)
        again = c2.until("question", kind="code_followup")
        assert again["turn_id"] == q["turn_id"] and again["tts"] is False
        c2.send(type="text_answer", turn_id=again["turn_id"], text="재접속 후 답변")
        assert c2.until("session_finished")["next"] == "coding"
    assert [t.answer_text for t in env.turns() if t.kind == TurnKind.CODE_FOLLOWUP] == ["재접속 후 답변"]


def test_finish_releases_the_session_slot_for_the_next_applicant(make_env):
    """POST /finish 가 런타임만 닫고 레지스트리에 남기면 MAX_CONCURRENT_SESSIONS=1 에서 다음 지원자가 영원히 시작하지 못한다 (E2E 에서 발견)."""
    brain = FakeBrain(total_main=1, max_followups=1, coding=True)
    env = make_env(slots=1, coding=True, brain=brain, extra_sessions=1)
    tok = env.tokens()
    with env.control(tok["control_token"]) as ws, env.media(tok["media_token"]) as mws:
        ctl = Ctl(ws)
        to_coding(env, ctl, mws)
        assert env.app.state.session_manager.get(env.session_id) is not None
        r = env.client.post(f"/api/v1/sessions/{env.session_id}/finish")
        assert r.status_code == 202
        env.wait_for(lambda: env.app.state.session_manager.get(env.session_id) is None, what="runtime discarded")
    assert len(env.app.state.session_manager._runtimes) == 0  # noqa: SLF001
