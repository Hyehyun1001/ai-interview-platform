"""Guardrail 실패 시 Retry · 꼬리질문 생략(백오프) · 이벤트 로그 (TRD §3.5 Retry 로직)."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.ai.chains.followup_chain import generate_followup
from app.ai.chains.prompts import FollowupInputs, MainQuestionInputs
from app.ai.chains.question_chain import generate_main_question
from app.ai.errors import GuardrailError, LLMUnavailable
from app.ai.guardrail import (DbGuardrailEventSink, GroundingContext, ListSink, generate_with_guardrail, run_with_guardrail,
                              verify_all)
from app.models import GuardrailEvent
from app.schemas.ai import FollowupDecision, MainQuestion
from tests.fakes import ScriptedFactory, followup_json, main_json

ANSWER = "Redis로 캐시를 붙여서 속도를 올렸어요. 그냥 TTL로 해결했고요."


def f_inputs(**kw) -> FollowupInputs:
    base = dict(question="캐시를 도입한 효과를 설명해 주세요.", answer=ANSWER, answer_ref="turn:1", resume_ctx='{"name":"김지원"}',
                resume_chunks={}, asked=["자기소개를 해주세요."], used=0, max_followups=2,
                triggers={"trigger_ambiguous": True, "trigger_contradiction": True, "trigger_stt_unclear": True})
    return FollowupInputs(**{**base, **kw})


def f_ctx() -> GroundingContext:
    return GroundingContext(answer_text=ANSWER, resume_text='{"name":"김지원"}', asked_questions=["자기소개를 해주세요."],
                            sources={"turn:1": ANSWER})


GOOD = followup_json()  # 키워드 Redis·캐시 — 답변에 있음
BAD_G2 = followup_json(keywords=["Kafka"], question="Kafka 파티션은 어떻게 나누셨나요?")  # 답변에 없는 키워드 → 환각
BAD_G4 = followup_json(question="결혼은 하셨나요?")
BAD_G6 = followup_json(question="캐시를 적용했습니다.")
NOT_JSON = "죄송합니다. 질문을 만들 수 없어요"
BAD_SCHEMA = '{"needed": true, "reason": "ambiguous", "grounding_keywords": [], "question": null}'  # needed=true 인데 질문 없음


# ── 성공 경로 ────────────────────────────────────────────────────────────────
async def test_first_attempt_success_records_passed_event():
    llm, sink = ScriptedFactory([GOOD]), ListSink()
    res = await generate_followup(llm, f_inputs(), f_ctx(), sink=sink)
    assert res.value.needed and res.attempts == 1 and not res.fell_back and res.failures == []
    assert [(e.check_id, e.outcome, e.attempt) for e in sink.events] == [("OK", "passed", 1)]
    assert llm.temperatures == [0.2]  # 1회차는 0.2


# ── 재시도 ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad,check", [(BAD_G2, "G2"), (BAD_G4, "G4"), (BAD_G6, "G6"), (NOT_JSON, "G1"), (BAD_SCHEMA, "G1")])
async def test_retry_succeeds_after_one_failure_with_reason_in_prompt_and_lower_temperature(bad, check):
    llm, sink = ScriptedFactory([bad, GOOD]), ListSink()
    res = await generate_followup(llm, f_inputs(), f_ctx(), sink=sink)
    assert res.value.needed and res.attempts == 2 and not res.fell_back
    assert llm.temperatures == [0.2, 0.3]  # 재시도는 0.3 (0.0 은 같은 출력을 반복시킨다, TRD §9.2)
    assert "[이전 시도 실패 사유]" not in llm.calls[0]["prompt"]
    assert "[이전 시도 실패 사유]" in llm.calls[1]["prompt"]  # 실패 사유가 재생성 프롬프트에 주입된다
    assert [(e.check_id, e.outcome) for e in sink.events] == [(check, "retry"), ("OK", "passed")]


async def test_g2_hint_names_the_offending_keyword_but_event_log_does_not():
    llm, sink = ScriptedFactory([BAD_G2, GOOD]), ListSink()
    await generate_followup(llm, f_inputs(), f_ctx(), sink=sink)
    assert "Kafka" in llm.calls[1]["prompt"]  # LLM 에게는 무엇이 틀렸는지 알려 준다
    assert all("Kafka" not in (e.reason or "") for e in sink.events)  # 저장되는 로그에는 사용자/LLM 텍스트가 없다


async def test_retry_hint_is_not_accumulated_beyond_last_failure():
    llm = ScriptedFactory([BAD_G2, BAD_G4, GOOD])
    await generate_followup(llm, f_inputs(), f_ctx())
    assert llm.calls[2]["prompt"].count("[이전 시도 실패 사유]") == 1
    assert "인적 속성" in llm.calls[2]["prompt"] and "Kafka" not in llm.calls[2]["prompt"]


# ── 3회 실패 → 꼬리질문 생략 ─────────────────────────────────────────────────
async def test_three_failures_skip_followup_instead_of_asking_a_bad_question():
    llm, sink = ScriptedFactory([BAD_G2, BAD_G4, BAD_G6, GOOD]), ListSink()
    res = await generate_followup(llm, f_inputs(), f_ctx(), sink=sink)
    assert res.fell_back and res.attempts == 3
    assert res.value == FollowupDecision.skip() and res.value.needed is False and res.value.question is None
    assert len(llm.calls) == 3 and llm.script == [GOOD]  # 4번째 호출은 없다
    assert [(e.check_id, e.outcome) for e in sink.events] == [("G2", "retry"), ("G4", "retry"), ("G6", "fallback")]
    assert llm.temperatures == [0.2, 0.3, 0.3]


async def test_max_attempts_is_configurable():
    llm = ScriptedFactory([BAD_G2, GOOD])
    res = await generate_followup(llm, f_inputs(), f_ctx(), max_attempts=1)
    assert res.fell_back and len(llm.calls) == 1


# ── 메인 질문 대체 ───────────────────────────────────────────────────────────
async def test_main_question_falls_back_to_bank_candidate_after_three_failures():
    bad = main_json(question="결혼은 하셨나요?")
    llm, sink = ScriptedFactory([bad, bad, bad]), ListSink()
    bank = MainQuestion(question="장애 대응 경험을 말씀해 주세요.", category="문제해결", evidence=[])
    res = await generate_main_question(
        llm, MainQuestionInputs("[업무] API 개발", "", "직무 역량", []), GroundingContext(), fallback=lambda: bank, sink=sink)
    assert res.fell_back and res.value == bank
    assert [e.outcome for e in sink.events] == ["retry", "retry", "fallback"]


async def test_main_question_accepts_valid_generation():
    llm = ScriptedFactory([main_json()])
    res = await generate_main_question(llm, MainQuestionInputs("jd", "", "기술", []), GroundingContext(), fallback=None)
    assert res.value.question.endswith("설명해 주세요.") and not res.fell_back


async def test_without_fallback_the_last_guardrail_error_is_raised():
    llm = ScriptedFactory([main_json(question="결혼은 하셨나요?")] * 3)
    with pytest.raises(GuardrailError) as e:
        await generate_main_question(llm, MainQuestionInputs("jd", "", "기술", []), GroundingContext(), fallback=None)
    assert e.value.check_id == "G4"
    assert len(llm.calls) == 3


async def test_async_fallback_is_awaited():
    async def fb() -> MainQuestion:
        return MainQuestion(question="대체 질문입니다. 말씀해 주세요.", category="기술", evidence=[])

    res = await generate_main_question(ScriptedFactory([main_json(question="결혼은 하셨나요?")] * 3),
                                       MainQuestionInputs("jd", "", "기술", []), GroundingContext(), fallback=fb)
    assert res.fell_back and "대체 질문" in res.value.question


# ── LLM 장애는 콘텐츠 실패와 다르다 ──────────────────────────────────────────
@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), ConnectionError("down"), httpx.ReadTimeout("slow")])
async def test_transport_errors_raise_llm_unavailable_without_retry(exc):
    llm = ScriptedFactory([exc, GOOD])
    with pytest.raises(LLMUnavailable):
        await generate_followup(llm, f_inputs(), f_ctx())
    assert len(llm.calls) == 1  # 연결 실패는 재시도하지 않고 호출자(경량 모드)에게 넘긴다


async def test_timeout_raises_llm_unavailable():
    llm = ScriptedFactory([GOOD], delay=0.5)
    with pytest.raises(LLMUnavailable):
        await generate_followup(llm, f_inputs(), f_ctx(), timeout_s=0.05)


async def test_unexpected_exception_is_not_swallowed():
    with pytest.raises(ZeroDivisionError):
        await generate_followup(ScriptedFactory([ZeroDivisionError()]), f_inputs(), f_ctx())


# ── 이벤트 싱크 ──────────────────────────────────────────────────────────────
async def test_sink_failure_never_breaks_generation():
    class Boom:
        async def record(self, event):  # noqa: ANN001, ANN201
            raise RuntimeError("db down")

    res = await generate_followup(ScriptedFactory([BAD_G2, GOOD]), f_inputs(), f_ctx(), sink=Boom())
    assert res.value.needed and res.attempts == 2


async def test_db_sink_persists_events_without_user_text(app, session):
    sink = DbGuardrailEventSink(app.state.sessionmaker)
    await generate_followup(ScriptedFactory([BAD_G2, BAD_G4, GOOD]), f_inputs(), f_ctx(), sink=sink)
    rows = (await session.execute(select(GuardrailEvent).order_by(GuardrailEvent.created_at))).scalars().all()
    assert [(r.chain, r.attempt, r.check_id, r.outcome) for r in rows] == [
        ("followup", 1, "G2", "retry"), ("followup", 2, "G4", "retry"), ("followup", 3, "OK", "passed")]
    joined = " ".join((r.reason or "") for r in rows)
    assert "Kafka" not in joined and "결혼" not in joined and all(len(r.reason or "") <= 300 for r in rows)


async def test_run_with_guardrail_accepts_custom_attempt_function():
    seen = []

    async def attempt(n, temperature, hint):  # noqa: ANN001, ANN201
        seen.append((n, temperature, hint))
        if n < 3:
            raise GuardrailError("G5", "dup")
        return "ok"

    res = await run_with_guardrail(attempt, chain_name="x", fallback=None)
    assert res.value == "ok" and res.attempts == 3
    assert [s[:2] for s in seen] == [(1, 0.2), (2, 0.3), (3, 0.3)] and seen[0][2] == "" and "dup" in seen[1][2]


async def test_verify_function_gets_parsed_pydantic_object():
    got = []
    llm = ScriptedFactory([GOOD])
    await generate_with_guardrail(lambda t: __import__("app.ai.chains.followup_chain", fromlist=["x"]).build_followup_chain(llm(t)),
                                  f_inputs().to_vars(), lambda r: got.append(r) or verify_all(r, f_ctx()),
                                  chain_name="followup", fallback=None)
    assert isinstance(got[0], FollowupDecision) and got[0].grounding_keywords == ["Redis", "캐시"]



async def test_wrong_schema_for_chain_is_classified_as_g1():
    """메인 질문 체인이 꼬리질문 JSON 형식을 받으면 스키마 위반(G1)으로 분류된다."""
    llm = ScriptedFactory([BAD_G4] * 3)
    with pytest.raises(GuardrailError) as e:
        await generate_main_question(llm, MainQuestionInputs("jd", "", "기술", []), GroundingContext(), fallback=None)
    assert e.value.check_id == "G1"
