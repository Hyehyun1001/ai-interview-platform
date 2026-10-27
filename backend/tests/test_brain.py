"""ChainBrain: 실제 DB + LCEL 체인 + Guardrail 이 맞물려 질문을 만든다 (TRD §3.4, §3.5, §2.3)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.ai.errors import LLMUnavailable
from app.ai.guardrail import DbGuardrailEventSink
from app.interview.brain import DEFAULT_MAIN_COUNT, ChainBrain, FollowupContext
from app.models import (Application, Company, FollowupRule, GuardrailEvent, InterviewSession, InterviewTurn, JobPosting,
                        JobQuestion, ResumeSnapshot, User)
from app.models.enums import ApplicationStatus, QuestionSource, SessionState, TurnKind, UserRole
from tests.fakes import ScriptedFactory, followup_json, main_json

CHUNK = "snap:experience:0"
CHUNK_TEXT = "[경력] (주)다온커머스 / 백엔드 개발자 Redis 캐시 도입으로 조회 응답 시간을 800ms 에서 200ms 로 개선"


async def seed(session, *, slots=None, manual=(), bank=(), rules=None, snapshot=True, coding=False, answer_limit=90):
    company = Company(name="다온")
    session.add(company)
    await session.flush()
    user = User(email=f"{uuid.uuid4().hex[:6]}@corp.local", password_hash="x", role=UserRole.APPLICANT, name="김지원")
    job = JobPosting(company_id=company.id, title="백엔드 개발자", status="open", duties="주문 결제 API 개발",
                     requirements="Java 경험", answer_time_limit_sec=answer_limit, coding_test_enabled=coding,
                     coding_test_time_limit_sec=1800 if coding else None)
    session.add_all([user, job])
    await session.flush()
    if rules:
        session.add(FollowupRule(job_id=job.id, **rules))
    for i, text in enumerate(manual):
        session.add(JobQuestion(job_id=job.id, source=QuestionSource.MANUAL, text=text, category="직접", time_limit_sec=45, order_no=i + 1))
    for text in bank:
        session.add(JobQuestion(job_id=job.id, source=QuestionSource.AI_BANK, text=text, category="은행"))
    app_ = Application(user_id=user.id, job_id=job.id, status=ApplicationStatus.PREPARED)
    session.add(app_)
    await session.flush()
    sess = InterviewSession(application_id=app_.id, state=SessionState.IN_PROGRESS,
                            precomputed_context={"slots": slots} if slots is not None else None)
    session.add(sess)
    if snapshot:
        session.add(ResumeSnapshot(application_id=app_.id, data={
            "name": "김지원", "experience": [{"company": "(주)다온커머스", "role": "백엔드 개발자"}],
            "skills": ["Java", "Redis"], "self_intro": "비밀스러운 자소서 본문 XYZ-SELF-INTRO"}))
    await session.commit()
    return sess.id


def brain(app, llm, **kw) -> ChainBrain:
    return ChainBrain(app.state.sessionmaker, llm, sink=DbGuardrailEventSink(app.state.sessionmaker), timeout_s=2, **kw)


SLOT = {"slot": 1, "query": "Redis", "resume": [{"chunk_id": CHUNK, "text": CHUNK_TEXT, "score": 0.8}],
        "jd": [{"chunk_id": "job:jd_duty:0", "text": "주문 결제 API 개발", "score": 0.7}]}


# ── 설정 ─────────────────────────────────────────────────────────────────────
async def test_load_config_reads_job_rules_and_slots(app, session):
    sid = await seed(session, slots=[{}, {}, {}], rules=dict(max_followups=3, trigger_contradiction=False), coding=True, answer_limit=90)
    cfg = await brain(app, ScriptedFactory()).load_config(sid)
    assert (cfg.total_main, cfg.answer_limit_sec, cfg.max_followups, cfg.coding_enabled, cfg.coding_limit_sec) == (3, 90, 3, True, 1800)
    assert cfg.triggers == {"trigger_ambiguous": True, "trigger_contradiction": False, "trigger_stt_unclear": True}


async def test_load_config_defaults_without_rules_or_slots(app, session):
    sid = await seed(session, slots=None, answer_limit=None)
    cfg = await brain(app, ScriptedFactory()).load_config(sid)
    assert cfg.total_main == DEFAULT_MAIN_COUNT == 10 and cfg.answer_limit_sec == 120 and cfg.max_followups == 2
    assert all(cfg.triggers.values()) and not cfg.coding_enabled


# ── 메인 질문 ────────────────────────────────────────────────────────────────
async def test_manual_question_is_used_as_is_without_calling_llm(app, session):
    llm = ScriptedFactory()
    sid = await seed(session, slots=[{}, SLOT], manual=["담당자가 직접 만든 질문입니다. 설명해 주세요."])
    d = await brain(app, llm).next_main_question(sid, 0, [])
    assert (d.text, d.category, d.time_limit_sec, d.source) == ("담당자가 직접 만든 질문입니다. 설명해 주세요.", "직접", 45, "manual")
    assert llm.calls == []  # 직접 등록한 질문에는 LLM·Guardrail 이 개입하지 않는다


async def test_generated_question_uses_precomputed_context_and_verifies_evidence(app, session):
    ev = [{"source": "resume", "ref": CHUNK, "quote": "Redis 캐시 도입으로 조회 응답 시간을 800ms 에서 200ms 로 개선"}]
    llm = ScriptedFactory([main_json(question="Redis 캐시로 응답 시간을 줄일 때 가장 어려웠던 점은 무엇인가요?", evidence=ev)])
    sid = await seed(session, slots=[{}, SLOT])
    d = await brain(app, llm).next_main_question(sid, 1, ["자기소개를 해주세요."])
    assert d.source == "generated" and d.text.startswith("Redis 캐시로") and d.evidence[0].ref == CHUNK and not d.degraded
    prompt = llm.calls[0]["prompt"]
    assert CHUNK in prompt and "800ms" in prompt and "주문 결제 API 개발" in prompt and "자기소개를 해주세요." in prompt
    assert llm.temperatures == [0.2]


async def test_resume_context_is_empty_when_no_slot_hits_so_question_stays_jd_based(app, session):
    llm = ScriptedFactory([main_json()])
    sid = await seed(session, slots=[{"slot": 0, "resume": [], "jd": [{"chunk_id": "j:0", "text": "API 개발", "score": 0.5}]}])
    await brain(app, llm).next_main_question(sid, 0, [])
    assert "[이력서 근거]\n<untrusted>\n(없음)\n</untrusted>" in llm.calls[0]["prompt"]  # 근거 없는 이력서 언급 차단 (TRD §3.3)


async def test_hallucinated_evidence_triggers_retry_then_success(app, session):
    fake = [{"source": "resume", "ref": CHUNK, "quote": "Kafka 로 이벤트 스트리밍 플랫폼을 설계했습니다 매우 크게"}]
    llm = ScriptedFactory([main_json(evidence=fake), main_json()])
    sid = await seed(session, slots=[SLOT])
    d = await brain(app, llm).next_main_question(sid, 0, [])
    assert d.source == "generated" and llm.temperatures == [0.2, 0.3] and "[이전 시도 실패 사유]" in llm.calls[1]["prompt"]


async def test_three_guardrail_failures_fall_back_to_unused_bank_candidate_and_log_events(app, session):
    bad = main_json(question="결혼은 하셨나요?")
    sid = await seed(session, slots=[SLOT], bank=["이미 물어본 은행 질문입니다. 말씀해 주세요.", "장애 대응 경험을 말씀해 주세요."])
    d = await brain(app, ScriptedFactory([bad] * 3), ).next_main_question(sid, 0, ["이미 물어본 은행 질문입니다. 말씀해 주세요."])
    assert d.source == "bank" and d.text == "장애 대응 경험을 말씀해 주세요." and not d.degraded  # 이미 한 후보는 건너뛴다
    rows = (await session.execute(select(GuardrailEvent).order_by(GuardrailEvent.created_at))).scalars().all()
    assert [(r.chain, r.check_id, r.outcome, r.session_id) for r in rows] == [("main_question", "G4", "retry", sid),
                                                                              ("main_question", "G4", "retry", sid),
                                                                              ("main_question", "G4", "fallback", sid)]


async def test_no_bank_left_uses_generic_job_question(app, session):
    sid = await seed(session, slots=[SLOT])
    d = await brain(app, ScriptedFactory([main_json(question="결혼은 하셨나요?")] * 3)).next_main_question(sid, 0, [])
    assert d.source == "generic" and "백엔드 개발자" in d.text and d.text.endswith("말씀해 주세요.")


async def test_llm_down_degrades_to_fallback_question_instead_of_failing_the_interview(app, session):
    sid = await seed(session, slots=[SLOT], bank=["장애 대응 경험을 말씀해 주세요."])
    d = await brain(app, ScriptedFactory([httpx.ConnectError("ollama down")])).next_main_question(sid, 0, [])
    assert d.degraded and d.source == "bank" and d.text == "장애 대응 경험을 말씀해 주세요."


# ── 꼬리질문 ─────────────────────────────────────────────────────────────────
def ctx(sid, **kw) -> FollowupContext:
    base = dict(session_id=sid, turn_id=uuid.uuid4(), question="캐시를 도입한 효과를 설명해 주세요.",
                answer="Redis로 캐시를 붙여서 속도를 올렸어요. 그냥 TTL로 해결했고요.", stt_unclear=False, asked=["자기소개를 해주세요."],
                used=0, max_followups=2)
    return FollowupContext(**{**base, **kw})


async def test_followup_streams_spoken_question_and_grounds_on_answer_and_resume(app, session):
    llm = ScriptedFactory([followup_json()])
    sid = await seed(session, slots=[SLOT], rules=dict(max_followups=2, trigger_contradiction=False))
    c, spoken = ctx(sid), []
    session.add(InterviewTurn(id=c.turn_id, session_id=sid, turn_no=1, kind=TurnKind.MAIN, main_index=0, question_text=c.question,
                              asked_at=datetime.now(timezone.utc)))  # 답변 중인 턴 (guardrail_events.turn_id FK)
    await session.commit()

    async def on_ready(p):  # noqa: ANN001, ANN202
        spoken.append(p.question)

    decision, early = await brain(app, llm).decide_followup(c, on_ready)
    assert decision.needed and early and spoken == [decision.question]
    prompt = llm.calls[0]["prompt"]
    assert f"turn:{c.turn_id}" in prompt and "(주)다온커머스" in prompt  # 답변 ref 와 이력서 JSON 이 근거로 제공된다
    assert "XYZ-SELF-INTRO" not in prompt  # 자소서 본문은 프롬프트에 넣지 않는다 (토큰 예산, ≤1,500 토큰)
    assert "이력서 내용과 모순" not in prompt and "답변이 모호함" in prompt  # 규칙에서 끈 발동 조건은 지시하지 않는다
    rows = (await session.execute(select(GuardrailEvent))).scalars().all()
    assert [(r.check_id, r.outcome, r.turn_id) for r in rows] == [("OK", "passed", c.turn_id)]


async def test_followup_three_failures_skip_without_speaking(app, session):
    sid = await seed(session, slots=[SLOT])
    spoken = []

    async def on_ready(p):  # noqa: ANN001, ANN202
        spoken.append(p)

    decision, early = await brain(app, ScriptedFactory([followup_json(keywords=["Kafka"], question="Kafka 는 왜 쓰셨나요?")] * 3)).decide_followup(
        ctx(sid), on_ready)
    assert not decision.needed and not early and spoken == []  # 환각 키워드로 만든 질문은 한 번도 음성이 되지 않는다


async def test_followup_without_resume_snapshot_still_works(app, session):
    llm = ScriptedFactory([followup_json()])
    sid = await seed(session, slots=[SLOT], snapshot=False)

    async def on_ready(p):  # noqa: ANN001, ANN202
        pass

    decision, _ = await brain(app, llm).decide_followup(ctx(sid), on_ready)
    assert decision.needed and "(이력서 없음)" in llm.calls[0]["prompt"]  # 기본 정보만 있는 지원자도 오류 없이 진행 (PRD 수용 기준)


async def test_followup_llm_unavailable_propagates_to_runtime(app, session):
    sid = await seed(session, slots=[SLOT])

    async def on_ready(p):  # noqa: ANN001, ANN202
        pass

    with pytest.raises(LLMUnavailable):
        await brain(app, ScriptedFactory([httpx.ConnectError("down")])).decide_followup(ctx(sid), on_ready)
